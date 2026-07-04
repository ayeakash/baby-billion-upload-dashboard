"""
csv_downloader.py — Download vertical videos from Google Drive (via Notion CSV)
and batch them for the BabyBillion upload pipeline.

Workflow:
  1. Load the app CSV (with playlist IDs, titles, metadata)
  2. Load the Notion CSV (with Drive links for in-house videos)
  3. Match by sanitized title to find the Drive link for each video
  4. Skip external/unmatched videos (no Notion entry = external channel)
  5. Download via gdown (Google Drive)
  6. Batch into ≤30 MB groups with admin CSVs
  7. Register in state.json + batches.json for the dashboard

Usage:
    python download_system/csv_downloader.py <playlist_id_1> [playlist_id_2 ...]

    Options:
        --dry-run       List videos that would be downloaded without downloading
        --batch-only    Skip downloads, just batch already-downloaded MP4s
        --csv <path>    Override the default app CSV file path
        --limit N       Download at most N videos (useful for testing)

Example:
    python download_system/csv_downloader.py 4e8e2dbf-bad4-4a56-8365-251a1cfc4a10
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import logging
import unicodedata
from datetime import datetime

# ── Resolve project paths ────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)                          # upload_dashboard/
PIPELINE_DIR = os.path.join(PROJECT_ROOT, "pipeline")

# Add pipeline/ to sys.path so we can reuse state_manager and downloader
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import state_manager as sm
from downloader import download_video  # reuse existing Drive download logic

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_CSV   = os.path.join(SCRIPT_DIR,
    "Latest Videos on The App 18th June - 28 Apr Duplicate.csv")
NOTION_CSV    = os.path.join(SCRIPT_DIR, "notion.csv")
PLAYLIST_MAPPING_CSV = os.path.join(SCRIPT_DIR,
    "Copy of Playlists Language Tagging - Playlist_new (1).csv")
CATEGORIES_MAPPING_CSV = os.path.join(PIPELINE_DIR, "categories mapping.csv")

DOWNLOADS_DIR = os.path.join(SCRIPT_DIR, "downloads")
BATCHES_DIR   = os.path.join(PROJECT_ROOT, "batches")
BATCHES_JSON  = os.path.join(PROJECT_ROOT, "batches.json")

MAX_BATCH_BYTES = 30 * 1024 * 1024   # 30 MB

ADMIN_CSV_HEADER = [
    "video_name", "categories_name", "age_groups",
    "channel_name", "tags", "playlist_name",
    "content_formats", "content_types", "language",
]

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("csv_downloader")


# ═══════════════════════════════════════════════════════════════════════════════
# SANITIZE / MATCHING
# ═══════════════════════════════════════════════════════════════════════════════

def sanitize_for_match(name: str) -> str:
    """Normalize a name for matching: lowercase, ASCII, underscores."""
    name = re.sub(r'[\u200b\u200c\u200d\u2060\ufeff\u2068\u2069]', '', name)
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"[\s]+", "_", name.strip())
    name = name.strip("_").lower()
    return name


def sanitize_filename(name: str) -> str:
    """Turn a video title into a safe, underscore-separated filename."""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^\w\s\-]", "", name)
    name = re.sub(r"[\s]+", "_", name.strip())
    return name[:120] or "untitled"


# ═══════════════════════════════════════════════════════════════════════════════
# LOAD NOTION CSV (Drive links)
# ═══════════════════════════════════════════════════════════════════════════════

def load_notion_drive_links(csv_path: str = NOTION_CSV) -> dict:
    """
    Build lookup: sanitized_video_name -> { hindi_link, english_link, ... }
    """
    lookup = {}
    if not os.path.isfile(csv_path):
        log.error(f"Notion CSV not found: {csv_path}")
        return lookup

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vname = (row.get("Video Name") or "").strip()
            if not vname:
                continue
            key = sanitize_for_match(vname)
            if not key:
                continue

            hindi_link   = (row.get("Final Video Hindi Link") or "").strip()
            english_link = (row.get("Final Video English Link") or "").strip()

            # Only store if there's at least one link
            if hindi_link or english_link:
                lookup[key] = {
                    "video_name_notion": vname,
                    "hindi_link":   hindi_link,
                    "english_link": english_link,
                    "category":     (row.get("Category") or "").strip(),
                    "age_group":    (row.get("Age Group") or "").strip(),
                    "status":       (row.get("Status") or "").strip(),
                }

    log.info(f"Loaded {len(lookup)} Notion videos with Drive links")
    return lookup


# ═══════════════════════════════════════════════════════════════════════════════
# PLAYLIST & CATEGORY MAPPING
# ═══════════════════════════════════════════════════════════════════════════════

def load_playlist_mapping(csv_path: str = PLAYLIST_MAPPING_CSV) -> dict:
    mapping = {}
    if not os.path.isfile(csv_path):
        log.warning(f"Playlist mapping CSV not found: {csv_path}")
        return mapping
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("playlist_id", "").strip().lower()
            if pid:
                mapping[pid] = {
                    "title":    row.get("title", "").strip(),
                    "language": row.get("Language", "Both").strip(),
                }
    log.info(f"Loaded {len(mapping)} playlist mappings")
    return mapping


def load_categories_mapping(csv_path: str = CATEGORIES_MAPPING_CSV) -> dict:
    mapping = {}
    if not os.path.isfile(csv_path):
        log.warning(f"Categories mapping CSV not found: {csv_path}")
        return mapping
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            age    = row.get("Age", "").strip()
            parent = row.get("Parent Category", "").strip()
            name   = row.get("Playlist Name", "").strip()
            if age and name:
                mapping[(age, name.lower())] = parent
    log.info(f"Loaded {len(mapping)} category mappings")
    return mapping


def resolve_category(age: str, playlist_name: str, cat_map: dict) -> str:
    key = (age, playlist_name.lower())
    parent = cat_map.get(key, "")
    if not parent:
        for (a, pn), par in cat_map.items():
            if a == age and (pn in playlist_name.lower() or playlist_name.lower() in pn):
                return par
    return parent


# ═══════════════════════════════════════════════════════════════════════════════
# CSV PARSING
# ═══════════════════════════════════════════════════════════════════════════════

def parse_age_buckets(raw: str) -> str:
    match = re.search(r'"S"\s*:\s*"([^"]+)"', raw)
    return match.group(1) if match else ""


def load_csv(csv_path: str) -> list[dict]:
    if not os.path.isfile(csv_path):
        log.error(f"CSV file not found: {csv_path}")
        sys.exit(1)
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    log.info(f"Loaded {len(rows)} rows from app CSV")
    return rows


def filter_by_playlists(rows: list[dict], playlist_ids: list[str],
                        pl_map: dict) -> list[dict]:
    pid_set = set(p.strip().lower() for p in playlist_ids)
    filtered = [r for r in rows if r.get("playlist_id", "").strip().lower() in pid_set]
    log.info(f"Filtered to {len(filtered)} videos across {len(pid_set)} playlist(s)")
    for pid in sorted(pid_set):
        count = sum(1 for r in filtered if r.get("playlist_id", "").strip().lower() == pid)
        pl_name = pl_map.get(pid, {}).get("title", "Unknown")
        log.info(f"  Playlist {pid[:8]}... ({pl_name}): {count} videos")
    return filtered


# ═══════════════════════════════════════════════════════════════════════════════
# DRIVE DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════════════

def download_all(videos: list[dict], pl_map: dict, notion_links: dict,
                 limit: int | None = None) -> list[dict]:
    """
    Download in-house videos from Google Drive.
    Skips external channel videos (no Notion match).
    Returns list of successfully downloaded video dicts.
    """
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    # First, filter to only videos with Notion matches
    matchable = []
    skipped_external = 0
    for row in videos:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        key = sanitize_for_match(title)
        if key in notion_links:
            matchable.append((row, notion_links[key]))
        else:
            skipped_external += 1

    log.info(f"  {len(matchable)} in-house videos matched (skipped {skipped_external} external)")

    if limit:
        matchable = matchable[:limit]
        log.info(f"  Limiting to first {limit} videos")

    total = len(matchable)
    downloaded = []
    failed = 0

    for i, (row, notion) in enumerate(matchable, 1):
        title       = row.get("title", "untitled")
        video_id    = row.get("video_id", "")
        age_group   = parse_age_buckets(row.get("age_buckets", ""))
        channel     = row.get("channel_name", "")
        playlist_id = row.get("playlist_id", "").strip().lower()

        # Resolve playlist name
        pl_info       = pl_map.get(playlist_id, {})
        playlist_name = pl_info.get("title", "")
        language      = pl_info.get("language", "Both")

        # Pick best Drive link: prefer Hindi link (original), fallback to English
        drive_link = notion.get("hindi_link") or notion.get("english_link") or ""
        if not drive_link:
            log.warning(f"  [{i}/{total}] No Drive link for '{title}' -- skipping")
            failed += 1
            continue

        safe_name = sanitize_filename(title)
        log.info(f"  [{i}/{total}] {title}  [{age_group}] [{playlist_name}]")

        # Reuse existing pipeline's download_video (handles files + folders)
        local_file = download_video(video_id, safe_name, drive_link)

        if local_file and os.path.isfile(local_file):
            # Move to our downloads dir if it ended up in pipeline's downloads
            our_path = os.path.join(DOWNLOADS_DIR, os.path.basename(local_file))
            if os.path.abspath(local_file) != os.path.abspath(our_path):
                shutil.move(local_file, our_path)
                local_file = our_path

            downloaded.append({
                "video_id":      video_id,
                "title":         title,
                "video_name":    safe_name,
                "age_group":     age_group,
                "channel_name":  channel,
                "local_file":    local_file,
                "playlist_id":   playlist_id,
                "playlist_name": playlist_name,
                "language":      language,
                "content_type":  row.get("content_type", "Original"),
                "video_url":     row.get("video_url", ""),
            })
        else:
            failed += 1

    log.info(f"\nDownload complete: {len(downloaded)} succeeded, {failed} failed out of {total}")
    return downloaded


# ═══════════════════════════════════════════════════════════════════════════════
# BATCHING
# ═══════════════════════════════════════════════════════════════════════════════

def _load_batches_json() -> dict:
    if os.path.isfile(BATCHES_JSON):
        try:
            with open(BATCHES_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Error reading batches.json: {e}")
    return {}


def _save_batches_json(batches: dict):
    tmp_file = BATCHES_JSON + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(batches, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, BATCHES_JSON)
    except Exception as e:
        log.error(f"Error saving batches.json: {e}")
        if os.path.isfile(tmp_file):
            try:
                os.remove(tmp_file)
            except:
                pass


def create_batches(videos: list[dict], cat_map: dict) -> list[str]:
    if not videos:
        log.info("No videos to batch.")
        return []

    os.makedirs(BATCHES_DIR, exist_ok=True)

    to_batch = []
    for v in videos:
        local = v.get("local_file", "")
        if local and os.path.isfile(local) and os.path.getsize(local) > 10_000:
            state_key = v["video_id"]
            rec = sm.get(state_key)
            if rec and rec.get("pipeline_status") in ("batched", "zipped", "uploading", "uploaded"):
                log.info(f"  [SKIP] Already batched: {v['video_name']}")
                continue
            to_batch.append(v)
        else:
            log.warning(f"  [WARN] No local file for: {v['video_name']}")

    if not to_batch:
        log.info("No new videos to batch.")
        return []

    # Deduplicate
    seen = {}
    deduped = []
    for v in to_batch:
        fname = os.path.basename(v["local_file"]).lower()
        if fname in seen:
            log.warning(f"  [DUPE] Skipping duplicate: {v['video_name']}")
            continue
        seen[fname] = v
        deduped.append(v)
    to_batch = deduped

    log.info(f"Batching {len(to_batch)} videos into <=30 MB batches ...")
    to_batch.sort(key=lambda v: v["video_name"])

    # Greedy bin-packing
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_size = 0

    for v in to_batch:
        file_size = os.path.getsize(v["local_file"])
        if current_batch and (current_size + file_size) > MAX_BATCH_BYTES:
            batches.append(current_batch)
            current_batch = []
            current_size = 0
        current_batch.append(v)
        current_size += file_size

    if current_batch:
        batches.append(current_batch)

    start_n = sm.next_batch_number(count=len(batches))
    all_batches_data = _load_batches_json()
    created = []

    for i, batch in enumerate(batches):
        batch_num    = start_n + i
        batch_name   = f"Batch_{batch_num:02d}"
        batch_folder = os.path.join(BATCHES_DIR, batch_name)
        batch_csv    = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
        os.makedirs(batch_folder, exist_ok=True)

        csv_rows = []
        batch_videos_meta = []

        for v in batch:
            fname = os.path.basename(v["local_file"])
            dst   = os.path.join(batch_folder, fname)
            if not os.path.isfile(dst):
                shutil.copy2(v["local_file"], dst)

            stem          = os.path.splitext(fname)[0]
            age           = v.get("age_group", "")
            playlist_name = v.get("playlist_name", "")
            parent_cat    = resolve_category(age, playlist_name, cat_map)

            # Derive language from ___ln_ suffix in filename
            if "___ln_Hi" in stem or "___ln_H" in stem:
                language = "Hindi"
            elif "___ln_En" in stem or "___ln_E" in stem:
                language = "English"
            else:
                language = ""

            # Strip language suffix from video_name (now in separate column)
            csv_video_name = re.sub(r"___ln_(Hi|En|H|E)$", "", stem)

            csv_rows.append({
                "video_name":      csv_video_name,
                "categories_name": playlist_name,
                "age_groups":      age,
                "channel_name":    v.get("channel_name", ""),
                "tags":            "",
                "playlist_name":   parent_cat,
                "content_formats": "",
                "content_types":   v.get("content_type", "Original"),
                "language":        language,
            })

            sm.upsert(
                v["video_id"],
                page_id=v["video_id"],
                video_name=v["video_name"],
                age_group=age,
                category=playlist_name,
                channel_name=v.get("channel_name", ""),
                local_file=v["local_file"],
                video_url=v.get("video_url", ""),
                pipeline_status="batched",
                batch=batch_name,
                source="csv_downloader",
            )

            batch_videos_meta.append({
                "page_id":         v["video_id"],
                "video_name":      v["video_name"],
                "age_group":       age,
                "category":        playlist_name,
                "local_file":      v["local_file"],
                "drive_link":      v.get("video_url", ""),
                "pipeline_status": "batched",
            })

        with open(batch_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ADMIN_CSV_HEADER)
            writer.writeheader()
            writer.writerows(csv_rows)

        all_batches_data[batch_name] = {
            "batch_name":     batch_name,
            "status":         "pending_first_review",
            "created_at":     datetime.now().isoformat(),
            "videos":         batch_videos_meta,
            "upload_job_id":  None,
            "upload_date":    None,
            "finalized_date": None,
        }

        size_mb = sum(
            os.path.getsize(os.path.join(batch_folder, f))
            for f in os.listdir(batch_folder) if f.endswith(".mp4")
        ) / (1024 * 1024)
        log.info(f"  {batch_name}: {len(batch)} videos, {size_mb:.1f} MB -> {batch_csv}")
        created.append(batch_name)

    _save_batches_json(all_batches_data)
    log.info(f"\nCreated {len(created)} batch(es): {', '.join(created)}")
    return created


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Download vertical videos from Drive and batch for upload.",
    )
    parser.add_argument("playlist_ids", nargs="+",
        help="One or more playlist UUIDs to download")
    parser.add_argument("--dry-run", action="store_true",
        help="List videos without downloading")
    parser.add_argument("--batch-only", action="store_true",
        help="Skip downloads, just batch already-downloaded files")
    parser.add_argument("--csv", default=DEFAULT_CSV,
        help="Path to the app CSV file")
    parser.add_argument("--limit", type=int, default=None,
        help="Max number of videos to download (for testing)")

    args = parser.parse_args()

    log.info("=" * 70)
    log.info("  CSV Downloader & Batcher (Drive links via Notion)")
    log.info("=" * 70)

    # ── Load mappings ─────────────────────────────────────────────────────────
    pl_map       = load_playlist_mapping()
    cat_map      = load_categories_mapping()
    notion_links = load_notion_drive_links()

    # ── Load and filter CSV ───────────────────────────────────────────────────
    rows     = load_csv(args.csv)
    filtered = filter_by_playlists(rows, args.playlist_ids, pl_map)

    if not filtered:
        log.warning("No videos found for the given playlist ID(s). Exiting.")
        sys.exit(0)

    # ── Match with Notion ─────────────────────────────────────────────────────
    matched_count = 0
    external_count = 0
    for row in filtered:
        title = (row.get("title") or "").strip()
        key = sanitize_for_match(title) if title else ""
        if key and key in notion_links:
            matched_count += 1
        else:
            external_count += 1

    log.info(f"\n  In-house (Notion match): {matched_count}")
    log.info(f"  External (skipped):      {external_count}")

    # ── Dry run ───────────────────────────────────────────────────────────────
    if args.dry_run:
        log.info("\n[DRY RUN] In-house videos that would be downloaded:\n")
        n = 0
        for row in filtered:
            title = (row.get("title") or "").strip()
            key   = sanitize_for_match(title) if title else ""
            if not key or key not in notion_links:
                continue
            n += 1
            age   = parse_age_buckets(row.get("age_buckets", ""))
            pid   = row.get("playlist_id", "").strip().lower()
            pl_name = pl_map.get(pid, {}).get("title", "?")
            notion  = notion_links[key]
            link    = notion.get("hindi_link") or notion.get("english_link") or "?"
            link_short = link[:60] + "..." if len(link) > 60 else link
            log.info(f"  {n:4d}. [{age}] {title}")
            log.info(f"        -> {link_short}")
        log.info(f"\nTotal: {n} in-house videos to download")
        return

    # ── Download ──────────────────────────────────────────────────────────────
    if args.batch_only:
        log.info("\n[BATCH-ONLY] Collecting existing files ...")
        downloaded = []
        for row in filtered:
            title     = (row.get("title") or "").strip()
            key       = sanitize_for_match(title) if title else ""
            if not key or key not in notion_links:
                continue
            safe_name   = sanitize_filename(title)
            local       = os.path.join(DOWNLOADS_DIR, f"{safe_name}.mp4")
            playlist_id = row.get("playlist_id", "").strip().lower()
            pl_info     = pl_map.get(playlist_id, {})

            if os.path.isfile(local) and os.path.getsize(local) > 10_000:
                downloaded.append({
                    "video_id":      row.get("video_id", ""),
                    "title":         title,
                    "video_name":    safe_name,
                    "age_group":     parse_age_buckets(row.get("age_buckets", "")),
                    "channel_name":  row.get("channel_name", ""),
                    "local_file":    local,
                    "playlist_id":   playlist_id,
                    "playlist_name": pl_info.get("title", ""),
                    "language":      pl_info.get("language", "Both"),
                    "content_type":  row.get("content_type", "Original"),
                    "video_url":     row.get("video_url", ""),
                })
        log.info(f"Found {len(downloaded)} already-downloaded videos")
    else:
        log.info(f"\nStarting download of in-house videos ...\n")
        downloaded = download_all(filtered, pl_map, notion_links, limit=args.limit)

    # ── Batch ─────────────────────────────────────────────────────────────────
    if downloaded:
        log.info(f"\nBatching {len(downloaded)} videos ...\n")
        created = create_batches(downloaded, cat_map)
        if created:
            log.info(f"\n{'='*70}")
            log.info(f"  Done! Created {len(created)} batch(es).")
            log.info(f"  Batches are in: {BATCHES_DIR}")
            log.info(f"  Registered in batches.json and state.json")
            log.info(f"{'='*70}")
    else:
        log.warning("No videos were downloaded/found. Nothing to batch.")


if __name__ == "__main__":
    main()
