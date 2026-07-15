"""
upload_swar_vyanjan.py — Re-download and re-upload all Varnmala videos,
splitting them into "Swar" (vowels) and "Vyanjan" (consonants) categories.

Steps:
  1. Find all Varnmala videos in state.json
  2. Classify each as Swar or Vyanjan based on filename
  3. Re-download from Google Drive (local files were cleaned up)
  4. Create batches (grouped by category, up to 30MB each)
  5. Upload each batch to admin.babybillion.in

Usage:
    python upload_swar_vyanjan.py          # full run (download + upload)
    python upload_swar_vyanjan.py --dry    # classify + show plan only
    python upload_swar_vyanjan.py --download-only  # download but don't upload
"""

import json
import sys
import os
import csv
import shutil
import time
import logging
import zipfile
import re

# Fix Windows console encoding for Hindi characters
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))

import state_manager as sm
from config import BATCHES_DIR, ADMIN_CSV_HEADER, ADMIN_CHANNEL_NAME, ADMIN_CONTENT_TYPE, DOWNLOADS_DIR, MAX_BATCH_BYTES
from category_mapper import get_category_fields
from downloader import download_video

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Hindi Swar (vowels) in Devanagari ──────────────────────────────────────────
SWAR_DEVANAGARI = set("अआइईउऊऋएऐओऔअंअः")


def classify_swar_or_vyanjan(video_name: str) -> str:
    """
    Classify a Varnmala video as 'Swar' or 'Vyanjan'.

    Rules:
      - If filename contains 'swar' (case-insensitive) → Swar
      - If filename contains any Devanagari vowel character → Swar
      - If filename contains 'vyanjan' (case-insensitive) → Vyanjan
      - Otherwise → Vyanjan (consonants are the default for numbered series)
    """
    name_lower = video_name.lower()

    # Check for explicit 'swar' in name
    if 'swar' in name_lower:
        return 'Swar'

    # Check for Devanagari vowel characters in the name
    for char in video_name:
        if char in SWAR_DEVANAGARI:
            return 'Swar'

    # Check for explicit 'vyanjan' in name
    if 'vyanjan' in name_lower:
        return 'Vyanjan'

    # Default: Vyanjan (consonants)
    return 'Vyanjan'


def _sanitize_video_name(stem):
    name = re.sub(r"[^\w\-]", "_", stem)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_").strip()
    return name or "untitled"


def collect_and_classify():
    """
    Find all Varnmala videos in state.json, classify them as Swar/Vyanjan,
    and return the list.
    """
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    videos = []
    for pid, rec in state.items():
        cat = rec.get("category", "")
        if cat.lower() not in ("varnamala", "varnmala", "swar", "vyanjan"):
            continue

        # If already reclassified, keep the existing category; otherwise classify
        if cat in ("Swar", "Vyanjan"):
            new_cat = cat
        else:
            new_cat = classify_swar_or_vyanjan(rec.get("video_name", ""))

        videos.append({
            "page_id":    pid,
            "video_name": rec.get("video_name", ""),
            "age_group":  rec.get("age_group", ""),
            "old_category": cat,
            "new_category": new_cat,
            "drive_link": rec.get("drive_link", ""),
            "local_file": rec.get("local_file", ""),
        })

    swar = [v for v in videos if v["new_category"] == "Swar"]
    vyanjan = [v for v in videos if v["new_category"] == "Vyanjan"]
    print(f"\n✓ Found {len(videos)} Varnmala videos: {len(swar)} Swar, {len(vyanjan)} Vyanjan")
    return videos


def update_state_categories(videos):
    """Update state.json with new Swar/Vyanjan categories and reset status to downloaded."""
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    old_batches = set()
    for v in videos:
        pid = v["page_id"]
        if pid in state:
            old_batch = state[pid].get("batch", "")
            if old_batch:
                old_batches.add(old_batch)

            state[pid]["category"] = v["new_category"]
            state[pid]["pipeline_status"] = "downloaded"
            state[pid].pop("error", None)
            state[pid].pop("batch", None)
            state[pid].pop("job_id", None)

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
        print(f"  Cleaned up old batch: {bname}")

    print(f"✓ Updated {len(videos)} videos in state.json")


def download_all(videos):
    """Re-download all videos from Google Drive."""
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    success = 0
    failed = 0
    skipped = 0

    for i, v in enumerate(sorted(videos, key=lambda x: x["video_name"]), 1):
        name = v["video_name"]
        drive_link = v["drive_link"]
        local_file = v.get("local_file", "")

        print(f"\n[{i}/{len(videos)}] {name}")

        # Check if already downloaded
        if local_file and os.path.isfile(local_file) and os.path.getsize(local_file) > 10_000:
            print(f"  SKIP (already exists): {os.path.basename(local_file)}")
            skipped += 1
            continue

        if not drive_link:
            print(f"  FAIL (no drive link)")
            failed += 1
            continue

        result = download_video(v["page_id"], name, drive_link)
        if result:
            # Update the local_file in state
            v["local_file"] = result
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            if v["page_id"] in state:
                state[v["page_id"]]["local_file"] = result
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            success += 1
        else:
            failed += 1

    print(f"\n✓ Download complete: {success} downloaded, {skipped} skipped, {failed} failed")
    return failed == 0


def make_batches(videos):
    """Create batches grouped by category (Swar/Vyanjan), up to MAX_BATCH_BYTES each."""
    os.makedirs(BATCHES_DIR, exist_ok=True)

    # Find next available batch number
    existing = 0
    for entry in os.listdir(BATCHES_DIR):
        if os.path.isdir(os.path.join(BATCHES_DIR, entry)):
            m = re.match(r"^Batch_(\d+)$", entry)
            if m:
                existing = max(existing, int(m.group(1)))

    # Group videos by category
    by_cat = {"Swar": [], "Vyanjan": []}
    skipped = []
    for v in sorted(videos, key=lambda x: x["video_name"]):
        local_file = v.get("local_file", "")

        # Re-check local file from state (may have been updated during download)
        if not local_file or not os.path.isfile(local_file):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            rec = state.get(v["page_id"], {})
            local_file = rec.get("local_file", "")
            v["local_file"] = local_file

        if not local_file or not os.path.isfile(local_file):
            print(f"  SKIP (no local file): {v['video_name']}")
            skipped.append(v["video_name"])
            continue

        by_cat.setdefault(v["new_category"], []).append(v)

    batch_names = []
    batch_num = existing

    for cat_name in ("Swar", "Vyanjan"):
        cat_videos = by_cat.get(cat_name, [])
        if not cat_videos:
            continue

        # Split into size-limited batches
        current_batch = []
        current_size = 0

        for v in cat_videos:
            fsize = os.path.getsize(v["local_file"])
            if current_batch and current_size + fsize > MAX_BATCH_BYTES:
                # Flush current batch
                batch_num += 1
                bname = _create_batch(batch_num, cat_name, current_batch)
                batch_names.append(bname)
                current_batch = []
                current_size = 0

            current_batch.append(v)
            current_size += fsize

        # Flush remaining
        if current_batch:
            batch_num += 1
            bname = _create_batch(batch_num, cat_name, current_batch)
            batch_names.append(bname)

    if skipped:
        print(f"\n⚠ Skipped {len(skipped)} videos (no local file):")
        for s in skipped:
            print(f"    {s}")

    print(f"\n✓ Created {len(batch_names)} batches")
    return batch_names


def _create_batch(batch_num, cat_name, batch_videos):
    """Create a single batch directory, CSV, and ZIP for a group of videos."""
    batch_name = f"Batch_{batch_num:02d}"
    batch_dir = os.path.join(BATCHES_DIR, batch_name)
    batch_csv = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
    batch_zip = os.path.join(BATCHES_DIR, f"{batch_name}.zip")
    os.makedirs(batch_dir, exist_ok=True)

    parent_cat, exact_cat = get_category_fields("3-6", cat_name)
    total_mb = 0

    rows = []
    files_for_zip = []

    for v in batch_videos:
        fname = os.path.basename(v["local_file"])
        dst = os.path.join(batch_dir, fname)
        if not os.path.isfile(dst):
            shutil.copy2(v["local_file"], dst)

        stem = os.path.splitext(fname)[0]
        video_name = _sanitize_video_name(stem)

        rows.append({
            "video_name":        video_name,
            "parent_categories": parent_cat,
            "age_groups":        "3-6",
            "channel_name":      ADMIN_CHANNEL_NAME,
            "tags":              "",
            "categories":        exact_cat,
            "content_formats":   "",
            "content_types":     ADMIN_CONTENT_TYPE,
        })

        files_for_zip.append((dst, fname))
        total_mb += os.path.getsize(dst) / 1024 / 1024

        # Update state
        sm.mark_batched(v["page_id"], batch_name)

    # Write CSV
    with open(batch_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ADMIN_CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)

    # Create ZIP
    with zipfile.ZipFile(batch_zip, "w", zipfile.ZIP_STORED) as zf:
        for filepath, arcname in files_for_zip:
            zf.write(filepath, arcname)

    print(f"  {batch_name}: [{cat_name}] {len(batch_videos)} videos ({total_mb:.1f} MB)")
    return batch_name


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
                sm.mark_failed(pid, "upload_failed_swar_vyanjan")

        time.sleep(3)  # pause between uploads

    driver.quit()

    print(f"\n{'='*60}")
    print(f"  RESULTS: {succeeded} succeeded, {failed} failed out of {len(batch_names)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    download_only = "--download-only" in sys.argv

    print("=" * 60)
    print("  Swar / Vyanjan Upload — Re-categorize Varnmala Videos")
    print("=" * 60)

    # Step 1: Classify
    videos = collect_and_classify()
    if not videos:
        print("No Varnmala videos found.")
        sys.exit(0)

    # Show classification
    print("\n--- SWAR (स्वर) ---")
    for v in sorted(videos, key=lambda x: x["video_name"]):
        if v["new_category"] == "Swar":
            print(f"  {v['video_name']}")

    print("\n--- VYANJAN (व्यंजन) ---")
    for v in sorted(videos, key=lambda x: x["video_name"]):
        if v["new_category"] == "Vyanjan":
            print(f"  {v['video_name']}")

    if dry:
        print("\n-- DRY RUN: showing plan only, no changes made --")
        sys.exit(0)

    # Step 2: Update state with new categories
    update_state_categories(videos)

    # Step 2b: Update categories in Notion
    print(f"\n{'='*60}")
    print("  Step 2b: Updating categories in Notion ...")
    print(f"{'='*60}")
    import notion_client as nc
    notion_ok = 0
    notion_fail = 0
    for v in videos:
        try:
            if nc.update_category_in_notion(v["page_id"], v["new_category"]):
                notion_ok += 1
            else:
                notion_fail += 1
        except Exception as e:
            log.warning(f"  Notion category update failed for {v['video_name']}: {e}")
            notion_fail += 1
    print(f"✓ Notion categories updated: {notion_ok} ok, {notion_fail} failed")

    # Step 3: Re-download all videos
    print(f"\n{'='*60}")
    print("  Step 3: Downloading videos from Google Drive ...")
    print(f"{'='*60}")
    all_ok = download_all(videos)

    if download_only:
        print("\n-- DOWNLOAD ONLY: stopping here --")
        sys.exit(0)

    # Step 4: Create batches
    print(f"\n{'='*60}")
    print("  Step 4: Creating batches ...")
    print(f"{'='*60}")
    batch_names = make_batches(videos)

    if not batch_names:
        print("No batches created. Check that videos were downloaded.")
        sys.exit(1)

    # Step 5: Upload
    print(f"\n{'='*60}")
    print("  Step 5: Uploading to admin.babybillion.in ...")
    print(f"{'='*60}")
    upload_all_batches(batch_names)
