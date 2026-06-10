"""
resplit_batches.py — Re-split oversized failing batches into smaller ones.

Batches 40, 42, 43, 44 are 17-20 MB and consistently hit "Failed to fetch"
server errors. This script:
  1. Reads each failing batch's CSV to find its videos
  2. Resets those videos back to 'downloaded' in state (so batcher can re-batch)
  3. Calls batcher.run() with the new 8 MB MAX_BATCH_BYTES limit
  4. Re-zips the new sub-batches
  5. Deletes old oversized batch folders / zips so they don't interfere

Usage:
    python resplit_batches.py
"""
import os, sys, csv, shutil, logging
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

import state_manager as sm
import batcher, zipper
from config import BATCHES_DIR, DOWNLOADS_DIR, MAX_BATCH_BYTES

# ── The batches to resplit ────────────────────────────────────────────────────
FAILED_BATCHES = ["Batch_40", "Batch_42", "Batch_43", "Batch_44"]

log.info(f"MAX_BATCH_BYTES = {MAX_BATCH_BYTES / 1024 / 1024:.1f} MB")
log.info(f"Resplitting: {FAILED_BATCHES}")

# ── Step 1: collect all videos from the failing batches ──────────────────────
state = sm.get_all()

# Build a lookup: batch_name -> list of page records
batch_to_pids = {}
for pid, rec in state.items():
    b = rec.get("batch")
    if b in FAILED_BATCHES:
        batch_to_pids.setdefault(b, []).append((pid, rec))

videos_to_rebatch = []
for batch_name in FAILED_BATCHES:
    entries = batch_to_pids.get(batch_name, [])
    log.info(f"\n{batch_name}: {len(entries)} video(s)")
    for pid, rec in entries:
        video_name = rec.get("video_name", "?")
        local_file = rec.get("local_file", "")

        # Try the downloads dir if local_file doesn't exist
        if not local_file or not os.path.isfile(local_file):
            # Look inside the batch folder for the MP4
            batch_folder = os.path.join(BATCHES_DIR, batch_name)
            if os.path.isdir(batch_folder):
                mp4s = [f for f in os.listdir(batch_folder) if f.lower().endswith(".mp4")]
                # Find the one whose stem matches the video name
                from downloader import sanitize_filename
                safe = sanitize_filename(video_name)
                match = next((f for f in mp4s if os.path.splitext(f)[0] == safe), None)
                if match:
                    # Copy it back to downloads/ if needed
                    src = os.path.join(batch_folder, match)
                    dst = os.path.join(DOWNLOADS_DIR, match)
                    if not os.path.isfile(dst):
                        shutil.copy2(src, dst)
                        log.info(f"  Copied {match} back to downloads/")
                    local_file = dst

        if not local_file or not os.path.isfile(local_file):
            log.warning(f"  [WARN] Cannot find local file for '{video_name}' — will skip")
            continue

        log.info(f"  {video_name}: {os.path.getsize(local_file)/1024/1024:.1f} MB  ({local_file})")

        # Reset to 'downloaded' so batcher sees it
        sm.mark_downloaded(pid, local_file)

        videos_to_rebatch.append({
            "page_id":    pid,
            "video_name": video_name,
            "age_group":  rec.get("age_group", ""),
            "category":   rec.get("category", ""),
            "drive_link": rec.get("drive_link", ""),
            "local_file": local_file,
        })

if not videos_to_rebatch:
    log.error("No videos found to re-batch. Exiting.")
    sys.exit(1)

log.info(f"\nTotal videos to re-batch: {len(videos_to_rebatch)}")

# ── Step 2: remove old oversized batch folders + zips ────────────────────────
for batch_name in FAILED_BATCHES:
    folder = os.path.join(BATCHES_DIR, batch_name)
    zip_f  = os.path.join(BATCHES_DIR, batch_name + ".zip")
    csv_f  = os.path.join(BATCHES_DIR, batch_name + ".csv")
    if os.path.isdir(folder):
        shutil.rmtree(folder)
        log.info(f"Removed folder: {folder}")
    if os.path.isfile(zip_f):
        os.remove(zip_f)
        log.info(f"Removed zip:    {zip_f}")
    if os.path.isfile(csv_f):
        os.remove(csv_f)
        log.info(f"Removed csv:    {csv_f}")

# ── Step 3: re-batch at new 8 MB limit ───────────────────────────────────────
log.info(f"\nRe-batching at {MAX_BATCH_BYTES/1024/1024:.0f} MB limit ...")
new_batches = batcher.run(videos_to_rebatch)
if not new_batches:
    log.error("batcher.run() returned no new batches — something went wrong.")
    sys.exit(1)

log.info(f"\nCreated {len(new_batches)} new batch(es): {new_batches}")

# ── Step 4: zip new batches ───────────────────────────────────────────────────
log.info("Zipping new batches ...")
zipper.zip_all(new_batches)

log.info("\n=== Done! ===")
log.info(f"New batches ready to upload: {new_batches}")
log.info("Run:  python retry_failed.py")
