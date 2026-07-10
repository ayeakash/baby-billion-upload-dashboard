"""
auto_upload.py — Unified CLI for batch → upload → submit → track.

Takes a folder of videos + metadata, then:
  1. Batches them by size limit
  2. Creates CSV + ZIP for each batch
  3. Registers in batches.json
  4. Uploads via Selenium to admin.babybillion.in
  5. Submits each batch for approval
  6. Tracks results (success/failed) in batches.json
  7. Prints a summary report

Usage:
    python auto_upload.py --source "path/to/videos" --channel Ms_Donna --category "Sing Along Rhymes" --playlist "English Basics" --age 0-3

    # Preview without uploading:
    python auto_upload.py --source "path/to/videos" --channel Ms_Donna --category "Sing Along Rhymes" --playlist "English Basics" --age 0-3 --dry-run

    # Custom batch size:
    python auto_upload.py --source "path/to/videos" --channel Ms_Donna --category "Sing Along Rhymes" --playlist "English Basics" --age 0-3 --batch-size 60

    # Skip upload (only batch + register):
    python auto_upload.py --source "path/to/videos" --channel Ms_Donna --category "Sing Along Rhymes" --playlist "English Basics" --age 0-3 --skip-upload
"""
from __future__ import annotations

import os
import sys
import csv
import json
import shutil
import zipfile
import argparse
import logging
import re
from datetime import date, datetime

# Force UTF-8 on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ── Setup paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(SCRIPT_DIR, "pipeline")
BATCHES_DIR = os.path.join(SCRIPT_DIR, "batches")
BATCHES_JSON = os.path.join(SCRIPT_DIR, "batches.json")

# Add pipeline to path for imports
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

# ── Logging ────────────────────────────────────────────────────────────────────
os.makedirs(os.path.join(SCRIPT_DIR, "logs"), exist_ok=True)
log_file = os.path.join(
    SCRIPT_DIR, "logs",
    f"auto_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── CSV header (must match admin site expectations) ────────────────────────────
CSV_HEADER = [
    "video_name", "categories_name", "age_groups", "channel_name",
    "tags", "playlist_name", "content_formats", "content_types", "language"
]


def detect_language(filename: str) -> str:
    """Detect language from filename suffix."""
    name = os.path.splitext(filename)[0]
    if name.endswith("_Hi") or name.endswith("_Hindi") or "_Hi_" in name:
        return "Hindi"
    elif name.endswith("_En") or name.endswith("_English") or "_En_" in name:
        return "English"
    # Default to English if no clear suffix
    return "English"


def clean_video_name(original: str) -> str:
    """Create a clean, filesystem-safe video name from the original filename."""
    name = os.path.splitext(original)[0]
    # Remove emoji and special chars, keep alphanumeric, spaces, hyphens, brackets
    name = re.sub(r'[^\w\s\-\[\]]', '', name)
    # Collapse whitespace to underscore
    name = re.sub(r'\s+', '_', name.strip())
    name = name.strip('_')
    return name


def get_next_batch_number() -> int:
    """Find the next available batch number from batches.json and batches/ folder."""
    max_num = 0

    # Check batches.json
    if os.path.isfile(BATCHES_JSON):
        try:
            with open(BATCHES_JSON, "r", encoding="utf-8") as f:
                batches = json.load(f)
            for bn in batches:
                if bn.startswith("Batch_"):
                    try:
                        num = int(bn.split("_")[1])
                        max_num = max(max_num, num)
                    except (ValueError, IndexError):
                        pass
        except Exception:
            pass

    # Check filesystem
    os.makedirs(BATCHES_DIR, exist_ok=True)
    for item in os.listdir(BATCHES_DIR):
        if item.startswith("Batch_"):
            name = item.split(".")[0]  # strip extension
            try:
                num = int(name.split("_")[1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                pass

    return max_num + 1


def load_batches_json() -> dict:
    """Load batches.json."""
    if os.path.isfile(BATCHES_JSON):
        try:
            with open(BATCHES_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_batches_json(data: dict):
    """Save batches.json atomically."""
    tmp = BATCHES_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, BATCHES_JSON)


def scan_videos(source_dir: str) -> list[dict]:
    """Scan source directory for video files and return metadata list."""
    videos = []
    for f in sorted(os.listdir(source_dir)):
        if f.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
            full_path = os.path.join(source_dir, f)
            size = os.path.getsize(full_path)
            videos.append({
                "original_filename": f,
                "clean_name": clean_video_name(f),
                "source_path": full_path,
                "size": size,
                "language": detect_language(f),
            })
    return videos


def create_batches(videos: list[dict], max_batch_bytes: int) -> list[list[dict]]:
    """Split videos into batches respecting size limit."""
    batches = []
    current = []
    current_size = 0

    for v in videos:
        if current_size + v["size"] > max_batch_bytes and current:
            batches.append(current)
            current = []
            current_size = 0
        current.append(v)
        current_size += v["size"]

    if current:
        batches.append(current)

    return batches


def build_batch_on_disk(
    batch_name: str,
    items: list[dict],
    channel: str,
    category: str,
    playlist: str,
    age: str,
    content_type: str,
    rename: bool,
) -> tuple[str, str, str]:
    """
    Create batch folder with videos, CSV, and ZIP.
    Returns (batch_dir, csv_path, zip_path).
    """
    batch_dir = os.path.join(BATCHES_DIR, batch_name)
    csv_path = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
    zip_path = os.path.join(BATCHES_DIR, f"{batch_name}.zip")

    os.makedirs(batch_dir, exist_ok=True)

    csv_rows = []
    for item in items:
        video_name = item["clean_name"] if rename else os.path.splitext(item["original_filename"])[0]
        dest_filename = f"{video_name}.mp4"
        dest_path = os.path.join(batch_dir, dest_filename)

        # Copy video
        shutil.copy2(item["source_path"], dest_path)
        item["batch_filename"] = dest_filename
        item["video_name"] = video_name

        csv_rows.append([
            video_name,
            category,
            age,
            channel,
            "",   # tags
            playlist,
            "",   # content_formats
            content_type,
            item["language"],
        ])

    # Write CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerows(csv_rows)

    # Create ZIP
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
        for item in items:
            zf.write(
                os.path.join(batch_dir, item["batch_filename"]),
                item["batch_filename"]
            )

    return batch_dir, csv_path, zip_path


def register_batch(batch_name: str, items: list[dict], channel: str,
                   category: str, playlist: str, age: str):
    """Register batch in batches.json for dashboard tracking."""
    batches = load_batches_json()

    batches[batch_name] = {
        "batch_name": batch_name,
        "status": "pending_first_review",
        "created_at": datetime.now().isoformat(),
        "source": "auto_upload",
        "videos": [
            {
                "page_id": f"manual_{batch_name}_{i}",
                "video_name": item["video_name"],
                "age_group": age,
                "category": category,
                "playlist": playlist,
                "channel": channel,
                "local_file": item["source_path"],
                "drive_link": "",
                "pipeline_status": "batched",
                "language": item["language"],
            }
            for i, item in enumerate(items)
        ],
        "upload_job_id": None,
        "upload_date": None,
        "upload_completed": False,
        "upload_failed": False,
        "fail_reason": None,
        "finalized_date": None,
    }

    save_batches_json(batches)

    # Also register in state.json so the Notion pipeline won't re-process these
    state_json = os.path.join(SCRIPT_DIR, "state.json")
    try:
        if os.path.isfile(state_json):
            with open(state_json, "r", encoding="utf-8") as f:
                state = json.load(f)
        else:
            state = {}

        for i, item in enumerate(items):
            state_key = f"manual_{batch_name}_{i}"
            state[state_key] = {
                "page_id": state_key,
                "video_name": item["video_name"],
                "age_group": age,
                "pipeline_status": "batched",
                "batch": batch_name,
                "source": "auto_upload",
                "updated_at": datetime.now().isoformat(),
            }

        tmp = state_json + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, state_json)
    except Exception as e:
        log.warning(f"  Could not update state.json: {e}")

    log.info(f"  Registered {batch_name} in batches.json + state.json ({len(items)} videos)")



def upload_and_submit(batch_names: list[str]) -> dict[str, dict]:
    """Upload batches and submit for approval using existing Selenium uploader."""
    try:
        import uploader
    except ImportError:
        log.error("Cannot import uploader.py — make sure pipeline/ is accessible")
        return {bn: {"job_id": None, "status": "upload_failed"} for bn in batch_names}

    log.info(f"\n{'='*60}")
    log.info(f"  UPLOADING {len(batch_names)} BATCH(ES)")
    log.info(f"{'='*60}\n")

    results = uploader.run_all_and_submit(batch_names, headless=False)

    # Update batches.json with results
    batches = load_batches_json()
    upload_date = date.today().isoformat()

    for bn, result in results.items():
        if bn not in batches:
            continue

        b = batches[bn]
        job_id = result.get("job_id")
        status = result.get("status", "upload_failed")

        if status == "submitted":
            b["upload_job_id"] = job_id
            b["upload_date"] = upload_date
            b["upload_completed"] = True
            b["upload_failed"] = False
            b["status"] = "pending_second_review"
            for v in b["videos"]:
                v["pipeline_status"] = "uploaded_pending_final_review"

        elif status == "approval_failed":
            b["upload_job_id"] = job_id
            b["upload_date"] = upload_date
            b["upload_completed"] = True
            b["upload_failed"] = True
            b["fail_reason"] = f"Uploaded (Job: {job_id}) but 'Submit for Approval' failed"
            for v in b["videos"]:
                v["pipeline_status"] = "uploaded_approval_failed"

        else:  # upload_failed
            b["upload_failed"] = True
            b["fail_reason"] = "Upload failed on admin site"
            for v in b["videos"]:
                v["pipeline_status"] = "upload_failed"

    save_batches_json(batches)

    # Sync Notion: submitted → 'Draft Upload', failed → 'Failed'
    try:
        import batch_manager
        sys.path.insert(0, os.path.join(SCRIPT_DIR, "pipeline"))
        import notion_client
        for bn, result in results.items():
            status = result.get("status", "upload_failed")
            job_id = result.get("job_id")
            if status == "submitted" and job_id:
                ok, msg = batch_manager.mark_batch_uploaded(bn, job_id)
                if ok:
                    log.info(f"  [NOTION] {bn}: {msg}")
                else:
                    log.warning(f"  [NOTION] {bn}: {msg}")
            elif status in ("upload_failed", "approval_failed"):
                # Mark Notion Upload Progress = 'Failed' for each video
                if bn in batches:
                    for v in batches[bn].get("videos", []):
                        pid = v.get("page_id", "")
                        if pid and not pid.startswith("manual_"):
                            try:
                                notion_client.mark_upload_failed_in_notion(pid)
                            except Exception:
                                pass
                    log.info(f"  [NOTION] {bn}: marked as Failed")
    except Exception as e:
        log.warning(f"  Could not sync Notion: {e}")

    # Update state.json for successfully uploaded videos
    state_json = os.path.join(SCRIPT_DIR, "state.json")
    try:
        if os.path.isfile(state_json):
            with open(state_json, "r", encoding="utf-8") as f:
                state = json.load(f)
        else:
            state = {}

        for bn, result in results.items():
            if bn not in batches:
                continue
            status = result.get("status", "upload_failed")
            job_id = result.get("job_id")
            for v in batches[bn].get("videos", []):
                sk = v.get("page_id", "")
                if sk and sk in state:
                    if status == "submitted":
                        state[sk]["pipeline_status"] = "uploaded"
                        state[sk]["job_id"] = job_id
                        state[sk]["upload_date"] = upload_date
                    elif status in ("upload_failed", "approval_failed"):
                        state[sk]["pipeline_status"] = status
                    state[sk]["updated_at"] = datetime.now().isoformat()

        tmp = state_json + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, state_json)
    except Exception as e:
        log.warning(f"Could not update state.json after upload: {e}")

    # Log to permanent upload history
    try:
        import upload_history
        for bn, result in results.items():
            if bn not in batches:
                continue
            status = result.get("status", "upload_failed")
            job_id = result.get("job_id", "")
            fail_reason = ""
            if status == "upload_failed":
                fail_reason = "Upload failed on admin site"
            elif status == "approval_failed":
                fail_reason = f"Uploaded but Submit for Approval failed"
            upload_history.log_batch(
                batch_name=bn,
                videos=batches[bn].get("videos", []),
                job_id=job_id or "",
                status=status,
                source="auto_upload",
                fail_reason=fail_reason,
            )
        log.info(f"  Upload history logged to upload_history.jsonl")
    except Exception as e:
        log.warning(f"Could not log upload history: {e}")

    return results


def print_summary(batch_results: list[dict]):
    """Print a nice summary report."""
    total = len(batch_results)
    submitted = sum(1 for r in batch_results if r["status"] == "submitted")
    upload_failed = sum(1 for r in batch_results if r["status"] == "upload_failed")
    approval_failed = sum(1 for r in batch_results if r["status"] == "approval_failed")
    skipped = sum(1 for r in batch_results if r["status"] == "skipped")

    log.info(f"\n{'='*60}")
    log.info(f"  SUMMARY REPORT")
    log.info(f"{'='*60}")
    log.info(f"  Total batches:     {total}")
    log.info(f"  ✅ Submitted:       {submitted}")
    if upload_failed:
        log.info(f"  ❌ Upload failed:   {upload_failed}")
    if approval_failed:
        log.info(f"  ⚠️  Approval failed: {approval_failed}")
    if skipped:
        log.info(f"  ⏭️  Skipped:         {skipped}")
    log.info(f"{'='*60}")

    for r in batch_results:
        icon = "✅" if r["status"] == "submitted" else "❌" if r["status"] == "upload_failed" else "⚠️"
        job_info = f" (Job: {r['job_id']})" if r.get("job_id") else ""
        log.info(f"  {icon} {r['batch_name']}: {r['status']}{job_info} — {r['video_count']} videos, {r['size_mb']:.1f} MB")

    log.info(f"\n  Log saved to: {log_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Unified batch → upload → submit → track for BabyBillion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage:
  python auto_upload.py --source "Ms Donna" --channel Ms_Donna --category "Sing Along Rhymes" --playlist "English Basics" --age 0-3

  # Preview only (no upload):
  python auto_upload.py --source "Ms Donna" --channel Ms_Donna --category "Sing Along Rhymes" --playlist "English Basics" --age 0-3 --dry-run

  # Custom batch size (60MB):
  python auto_upload.py --source "Ms Donna" --channel Ms_Donna --category "Sing Along Rhymes" --playlist "English Basics" --age 0-3 --batch-size 60

  # Batch + register only, skip Selenium upload:
  python auto_upload.py --source "Ms Donna" --channel Ms_Donna --category "Sing Along Rhymes" --playlist "English Basics" --age 0-3 --skip-upload
        """
    )
    parser.add_argument("--source", required=True, help="Path to folder containing video files")
    parser.add_argument("--channel", required=True, help="Channel name (e.g., Ms_Donna, BabyBillion_Education)")
    parser.add_argument("--category", required=True, help="Category name (e.g., 'Sing Along Rhymes')")
    parser.add_argument("--playlist", required=True, help="Playlist name (e.g., 'English Basics')")
    parser.add_argument("--age", required=True, choices=["0-3", "3-6", "6+"], help="Age group")
    parser.add_argument("--content-type", default="Original", help="Content type (default: Original)")
    parser.add_argument("--batch-size", type=int, default=30, help="Max batch size in MB (default: 30)")
    parser.add_argument("--rename", action="store_true", help="Clean/rename video filenames (strip emoji, etc.)")
    parser.add_argument("--dry-run", action="store_true", help="Preview batches without creating or uploading")
    parser.add_argument("--skip-upload", action="store_true", help="Create batches + register, but don't upload via Selenium")

    args = parser.parse_args()

    # Validate source directory
    source_dir = os.path.abspath(args.source)
    if not os.path.isdir(source_dir):
        log.error(f"Source directory not found: {source_dir}")
        sys.exit(1)

    max_batch_bytes = args.batch_size * 1024 * 1024

    log.info(f"{'='*60}")
    log.info(f"  AUTO UPLOAD")
    log.info(f"{'='*60}")
    log.info(f"  Source:      {source_dir}")
    log.info(f"  Channel:     {args.channel}")
    log.info(f"  Category:    {args.category}")
    log.info(f"  Playlist:    {args.playlist}")
    log.info(f"  Age group:   {args.age}")
    log.info(f"  Content:     {args.content_type}")
    log.info(f"  Batch size:  {args.batch_size} MB")
    log.info(f"  Rename:      {args.rename}")
    log.info(f"  Dry run:     {args.dry_run}")
    log.info(f"  Skip upload: {args.skip_upload}")
    log.info(f"{'='*60}\n")

    # ── Step 1: Scan videos ──────────────────────────────────────────────────
    videos = scan_videos(source_dir)
    if not videos:
        log.error("No video files found in source directory!")
        sys.exit(1)

    total_size = sum(v["size"] for v in videos)
    log.info(f"Found {len(videos)} videos ({total_size / (1024*1024):.1f} MB total)")

    # ── Step 1b: Dedup — skip videos already uploaded (state.json) ────────────
    state_json = os.path.join(SCRIPT_DIR, "state.json")
    uploaded_names = set()
    if os.path.isfile(state_json):
        try:
            with open(state_json, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            for _key, rec in state_data.items():
                if not isinstance(rec, dict):
                    continue
                # Only block if actually uploaded — not just batched/in-progress
                if rec.get("pipeline_status") == "uploaded":
                    vname = rec.get("video_name", "")
                    if vname:
                        uploaded_names.add(vname.lower().strip())
        except Exception as e:
            log.warning(f"Could not read state.json for dedup: {e}")

    # Filter out already-uploaded videos
    skipped = 0
    new_videos = []
    for v in videos:
        clean = v["clean_name"].lower().strip()
        orig_stem = os.path.splitext(v["original_filename"])[0].lower().strip()

        if clean in uploaded_names or orig_stem in uploaded_names:
            skipped += 1
            log.info(f"  [SKIP] Already uploaded: {v['original_filename']}")
            continue
        new_videos.append(v)

    if skipped:
        log.info(f"\n  Dedup: {skipped} already uploaded — skipped")
        log.info(f"  {len(new_videos)} new videos to process\n")

    videos = new_videos
    if not videos:
        log.info("All videos have already been uploaded. Nothing to do.")
        return


    # ── Step 2: Create batches ───────────────────────────────────────────────
    batch_chunks = create_batches(videos, max_batch_bytes)
    next_num = get_next_batch_number()

    log.info(f"Will create {len(batch_chunks)} batch(es) starting from Batch_{next_num}:\n")
    for i, chunk in enumerate(batch_chunks):
        batch_name = f"Batch_{next_num + i}"
        chunk_size = sum(v["size"] for v in chunk)
        log.info(f"  {batch_name}: {len(chunk)} videos, {chunk_size / (1024*1024):.1f} MB")
        for v in chunk:
            log.info(f"    • {v['original_filename']} ({v['size'] / (1024*1024):.1f} MB) [{v['language']}]")

    if args.dry_run:
        log.info(f"\n{'='*60}")
        log.info(f"  DRY RUN — no files created, no uploads performed")
        log.info(f"{'='*60}")
        return

    # ── Step 3: Build batches on disk ────────────────────────────────────────
    log.info(f"\nCreating batch folders, CSVs, and ZIPs...")
    batch_names = []
    batch_results = []

    for i, chunk in enumerate(batch_chunks):
        batch_name = f"Batch_{next_num + i}"
        batch_names.append(batch_name)

        log.info(f"\n  Building {batch_name}...")
        batch_dir, csv_path, zip_path = build_batch_on_disk(
            batch_name=batch_name,
            items=chunk,
            channel=args.channel,
            category=args.category,
            playlist=args.playlist,
            age=args.age,
            content_type=args.content_type,
            rename=args.rename,
        )

        zip_size = os.path.getsize(zip_path) / (1024 * 1024)
        log.info(f"    Folder: {batch_dir}")
        log.info(f"    CSV:    {csv_path}")
        log.info(f"    ZIP:    {zip_path} ({zip_size:.1f} MB)")

        # Register in batches.json
        register_batch(
            batch_name=batch_name,
            items=chunk,
            channel=args.channel,
            category=args.category,
            playlist=args.playlist,
            age=args.age,
        )

        batch_results.append({
            "batch_name": batch_name,
            "video_count": len(chunk),
            "size_mb": zip_size,
            "status": "created",
            "job_id": None,
        })

    # ── Step 4: Upload + Submit ──────────────────────────────────────────────
    if args.skip_upload:
        log.info(f"\n{'='*60}")
        log.info(f"  SKIP UPLOAD — {len(batch_names)} batch(es) created and registered")
        log.info(f"  Use the dashboard to upload them, or run without --skip-upload")
        log.info(f"{'='*60}")
        for r in batch_results:
            r["status"] = "skipped"
        print_summary(batch_results)
        return

    # Upload and submit
    upload_results = upload_and_submit(batch_names)

    # Merge upload results into batch_results
    for r in batch_results:
        bn = r["batch_name"]
        if bn in upload_results:
            ur = upload_results[bn]
            r["status"] = ur.get("status", "upload_failed")
            r["job_id"] = ur.get("job_id")
        else:
            r["status"] = "upload_failed"

    # ── Step 5: Summary ──────────────────────────────────────────────────────
    print_summary(batch_results)


if __name__ == "__main__":
    main()
