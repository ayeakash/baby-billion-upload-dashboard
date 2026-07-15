"""
upload_varnmala.py — Upload all Varnmala videos using 1-video-per-batch
to avoid "Failed to fetch" server errors.

Usage:
    python upload_varnmala.py          # full run
    python upload_varnmala.py --dry    # fix state + show plan only
"""

import json
import sys
import os
import csv
import shutil
import time
import logging

# Fix Windows console encoding for Hindi characters
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))

import state_manager as sm
from config import BATCHES_DIR, ADMIN_CSV_HEADER, ADMIN_CHANNEL_NAME, ADMIN_CONTENT_TYPE
from category_mapper import get_category_fields

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def _sanitize_video_name(stem):
    import re
    name = re.sub(r"[^\w\-]", "_", stem)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_").strip()
    return name or "untitled"


def reset_and_collect():
    """
    Reset all Varnmala videos to 'downloaded' status, clean up any
    existing batch artifacts, and return the list of videos.
    """
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    videos = []
    old_batches = set()

    for pid, rec in state.items():
        cat = rec.get("category", "")
        if cat.lower() not in ("varnamala", "varnmala"):
            continue

        # Collect old batch names for cleanup
        old_batch = rec.get("batch", "")
        if old_batch:
            old_batches.add(old_batch)

        # Fix category and reset status
        rec["category"] = "Varnmala"
        rec["pipeline_status"] = "downloaded"
        rec.pop("error", None)
        rec.pop("batch", None)

        local_file = rec.get("local_file", "")
        if not local_file or not os.path.isfile(local_file):
            print(f"  SKIP (no local file): {rec.get('video_name', pid)}")
            continue

        videos.append({
            "page_id":    pid,
            "video_name": rec.get("video_name", ""),
            "age_group":  rec.get("age_group", ""),
            "category":   "Varnmala",
            "drive_link": rec.get("drive_link", ""),
            "local_file": local_file,
        })

    # Save updated state
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    # Clean up old batch artifacts
    for bname in old_batches:
        batch_dir = os.path.join(BATCHES_DIR, bname)
        if os.path.isdir(batch_dir):
            shutil.rmtree(batch_dir)
        for ext in (".csv", ".zip"):
            bf = os.path.join(BATCHES_DIR, f"{bname}{ext}")
            if os.path.isfile(bf):
                os.remove(bf)
        print(f"  Cleaned up: {bname}")

    print(f"\n✓ {len(videos)} Varnmala videos reset to 'downloaded'")
    return videos


def make_single_batches(videos):
    """Create one batch per video for maximum server compatibility."""
    import zipfile

    os.makedirs(BATCHES_DIR, exist_ok=True)

    # Find next available batch number
    existing = 0
    for entry in os.listdir(BATCHES_DIR):
        if os.path.isdir(os.path.join(BATCHES_DIR, entry)):
            import re
            m = re.match(r"^Batch_(\d+)$", entry)
            if m:
                existing = max(existing, int(m.group(1)))

    batch_names = []
    for i, v in enumerate(sorted(videos, key=lambda x: x["video_name"]), existing + 1):
        batch_name = f"Batch_{i:02d}"
        batch_dir = os.path.join(BATCHES_DIR, batch_name)
        batch_csv = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
        batch_zip = os.path.join(BATCHES_DIR, f"{batch_name}.zip")
        os.makedirs(batch_dir, exist_ok=True)

        # Copy video
        fname = os.path.basename(v["local_file"])
        dst = os.path.join(batch_dir, fname)
        if not os.path.isfile(dst):
            shutil.copy2(v["local_file"], dst)

        # Create CSV
        stem = os.path.splitext(fname)[0]
        video_name = _sanitize_video_name(stem)
        parent_cat, exact_cat = get_category_fields("3-6", "Varnmala")

        row = {
            "video_name":        video_name,
            "parent_categories": parent_cat,
            "age_groups":        "3-6",
            "channel_name":      ADMIN_CHANNEL_NAME,
            "tags":              "",
            "categories":        exact_cat,
            "content_formats":   "",
            "content_types":     ADMIN_CONTENT_TYPE,
        }

        with open(batch_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ADMIN_CSV_HEADER)
            writer.writeheader()
            writer.writerow(row)

        # Create ZIP
        with zipfile.ZipFile(batch_zip, "w", zipfile.ZIP_STORED) as zf:
            zf.write(dst, fname)

        # Update state
        sm.mark_batched(v["page_id"], batch_name)

        size_mb = os.path.getsize(dst) / 1024 / 1024
        print(f"  {batch_name}: {video_name} ({size_mb:.1f} MB)")
        batch_names.append(batch_name)

    print(f"\n✓ Created {len(batch_names)} single-video batches")
    return batch_names


def upload_all_batches(batch_names):
    """Upload each single-video batch."""
    import uploader
    import notion_client as nc
    from datetime import date

    today = date.today().isoformat()

    driver = uploader.build_driver(headless=False)
    logged_in = uploader.login(driver)
    if not logged_in:
        log.error("Login failed!")
        driver.quit()
        return

    succeeded = 0
    failed = 0

    for i, bname in enumerate(batch_names, 1):
        print(f"\n{'='*60}")
        print(f"  [{i}/{len(batch_names)}] Uploading {bname} ...")
        print(f"{'='*60}")

        job_id = uploader.upload_batch(driver, bname)

        # Get videos in this batch
        state = sm.get_all()
        batch_pids = [pid for pid, rec in state.items() if rec.get("batch") == bname]

        if job_id:
            succeeded += 1
            log.info(f"  ✓ {bname} → job_id={job_id}")
            for pid in batch_pids:
                sm.mark_uploaded(pid, job_id, today)
                try:
                    nc.mark_uploaded_in_notion(pid, today)
                except Exception as e:
                    log.warning(f"  Notion update failed for {pid}: {e}")

            # Cleanup batch artifacts
            try:
                batch_dir = os.path.join(BATCHES_DIR, bname)
                if os.path.isdir(batch_dir):
                    shutil.rmtree(batch_dir)
                for ext in (".csv", ".zip"):
                    bf = os.path.join(BATCHES_DIR, f"{bname}{ext}")
                    if os.path.isfile(bf):
                        os.remove(bf)
            except Exception:
                pass
        else:
            failed += 1
            log.error(f"  ✗ {bname} FAILED")
            for pid in batch_pids:
                sm.mark_failed(pid, "upload_failed_to_fetch")

        time.sleep(3)  # pause between uploads

    driver.quit()

    print(f"\n{'='*60}")
    print(f"  RESULTS: {succeeded} succeeded, {failed} failed out of {len(batch_names)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    dry = "--dry" in sys.argv

    print("=" * 60)
    print("  Varnmala Upload — Single-Video Batches")
    print("=" * 60)

    videos = reset_and_collect()
    if not videos:
        print("No videos to process.")
        sys.exit(0)

    if dry:
        print("\n-- DRY RUN: state fixed but not uploading --")
        for v in videos:
            size_mb = os.path.getsize(v["local_file"]) / 1024 / 1024
            print(f"  {v['video_name'][:50]:50s}  {size_mb:.1f} MB")
        sys.exit(0)

    batch_names = make_single_batches(videos)
    upload_all_batches(batch_names)
