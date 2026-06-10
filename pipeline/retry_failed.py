"""
retry_failed.py — Re-upload all failed videos.

Handles three cases:
  1. 'retry_no_job_id' failures  → zip already exists, just re-upload the batch
  2. 'upload_no_job_id' failures → re-download + re-batch + re-upload
  3. 'downloaded' videos         → already on disk, just re-batch + re-upload

Usage:
    python retry_failed.py [--headless] [--delay N]
"""
import os, sys, time, argparse, logging
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(__file__))

os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
log_path = os.path.join(os.path.dirname(__file__), "logs",
    f"retry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[logging.FileHandler(log_path, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

import state_manager as sm
import notion_client  as nc
import batcher, zipper, uploader, downloader

TODAY = date.today().isoformat()

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--delay",    type=int, default=15,
                    help="Seconds to wait between batch uploads (default 15)")
args = parser.parse_args()

# ── Collect pending work ──────────────────────────────────────────────────────
state = sm.get_all()

# ── CASE 1: retry_no_job_id — zip exists, re-mark as batched, then upload ────
retry_batches_to_restore = set()
for pid, rec in state.items():
    if (rec.get("pipeline_status") == "failed"
            and rec.get("failure_reason") == "retry_no_job_id"
            and rec.get("batch")):
        batch = rec["batch"]
        zip_path = os.path.join(os.path.dirname(__file__), "batches", batch + ".zip")
        if os.path.isfile(zip_path):
            retry_batches_to_restore.add(batch)

log.info(f"Case 1  retry_no_job_id batches to re-upload: {len(retry_batches_to_restore)}")

# Reset their state back to 'batched' so the upload loop picks them up
if retry_batches_to_restore:
    log.info("  Resetting retry_no_job_id entries -> batched ...")
    for pid, rec in sm.get_all().items():
        if (rec.get("pipeline_status") == "failed"
                and rec.get("failure_reason") == "retry_no_job_id"
                and rec.get("batch") in retry_batches_to_restore):
            sm.mark_batched(pid, rec["batch"])

# ── CASE 2: upload_no_job_id — no local file, need full re-download ──────────
need_download = [
    {
        "page_id":    pid,
        "video_name": rec["video_name"],
        "age_group":  rec.get("age_group", ""),
        "category":   rec.get("category", ""),
        "drive_link": rec.get("drive_link", ""),
        "local_file": rec.get("local_file", ""),
    }
    for pid, rec in state.items()
    if rec.get("pipeline_status") == "failed"
    and rec.get("failure_reason") == "upload_no_job_id"
    and not (rec.get("local_file") and os.path.isfile(rec.get("local_file", "")))
    and rec.get("drive_link")
]
log.info(f"Case 2  upload_no_job_id (need re-download): {len(need_download)}")

# Re-download them
downloaded_ok = []
if need_download:
    log.info("  Re-downloading missing videos ...")
    for item in need_download:
        pid  = item["page_id"]
        name = item["video_name"]
        link = item["drive_link"]
        log.info(f"    Downloading: {name}")
        local = downloader.download_video(pid, name, link)
        if local:
            sm.mark_downloaded(pid, local)
            item["local_file"] = local
            downloaded_ok.append(item)
            log.info(f"    [OK] {name}")
        else:
            log.error(f"    [FAIL] Could not download: {name}")

# ── CASE 3: already downloaded but not yet batched ───────────────────────────
already_downloaded = [
    {
        "page_id":    pid,
        "video_name": rec["video_name"],
        "age_group":  rec.get("age_group", ""),
        "category":   rec.get("category", ""),
        "drive_link": rec.get("drive_link", ""),
        "local_file": rec.get("local_file", ""),
    }
    for pid, rec in sm.get_all().items()   # re-load after downloads
    if rec.get("pipeline_status") == "downloaded"
    and rec.get("local_file")
    and os.path.isfile(rec.get("local_file", ""))
]
log.info(f"Case 3  already downloaded (need batching): {len(already_downloaded)}")

# ── Re-batch cases 2 + 3 ─────────────────────────────────────────────────────
videos_to_batch = downloaded_ok + already_downloaded

# ── Dedup guard: filter out content already uploaded in a prior run ───────────
from dedup_utils import normalize_video_key, build_uploaded_keys_from_state
uploaded_keys = build_uploaded_keys_from_state(sm.get_all())
safe_to_batch = []
for v in videos_to_batch:
    key = normalize_video_key(v.get("video_name", ""), v.get("age_group", ""))
    if key in uploaded_keys:
        log.warning(
            f"  [DUPE-UPLOAD] Skipping '{v['video_name']}' "
            f"(age={v.get('age_group','?')}) — already uploaded in a prior run"
        )
        continue
    safe_to_batch.append(v)
if len(safe_to_batch) < len(videos_to_batch):
    log.info(f"  Removed {len(videos_to_batch) - len(safe_to_batch)} already-uploaded video(s).")
videos_to_batch = safe_to_batch

new_batch_names = []
if videos_to_batch:
    log.info(f"Re-batching {len(videos_to_batch)} video(s) ...")
    new_batch_names = batcher.run(videos_to_batch) or []
    if new_batch_names:
        log.info(f"  Created {len(new_batch_names)} new batch(es): {new_batch_names}")
        log.info("  Zipping new batches ...")
        zipper.zip_all(new_batch_names)

# ── Gather all batches to upload ─────────────────────────────────────────────
# Re-load fresh state (after resets + new batching)
fresh_state = sm.get_all()
pending_batches = sorted({
    rec["batch"]
    for rec in fresh_state.values()
    if rec.get("pipeline_status") == "batched" and rec.get("batch")
})

all_batches = pending_batches  # retry_no_job_id are now 'batched' again
log.info(f"Total batches to upload: {len(all_batches)}: {all_batches}")

if not all_batches:
    log.info("Nothing to upload.")
    sys.exit(0)

# ── Upload ───────────────────────────────────────────────────────────────────
log.info(f"Starting uploads ({args.delay}s delay on failure) ...")
driver = uploader.build_driver(headless=args.headless)
if not uploader.login(driver):
    log.error("Login failed")
    driver.quit()
    sys.exit(1)

# ── Heartbeat: prints live progress every 30s ─────────────────────────────────
import threading
_stop_heartbeat = threading.Event()
_current_batch  = ["—"]

def _heartbeat():
    while not _stop_heartbeat.wait(30):
        try:
            counts = sm.summary()
            up  = counts.get("uploaded", 0)
            bat = counts.get("batched",  0)
            fail= counts.get("failed",   0)
            now = datetime.now().strftime("%H:%M:%S")
            print(f"\n[{now}] >> Retry | current: {_current_batch[0]}"
                  f" | uploaded={up}  batched={bat}  failed={fail}", flush=True)
        except Exception:
            pass

threading.Thread(target=_heartbeat, daemon=True, name="heartbeat").start()

ok, fail = 0, 0
for i, bname in enumerate(all_batches, 1):
    _current_batch[0] = f"{bname} ({i}/{len(all_batches)})"
    log.info(f"\n[{i}/{len(all_batches)}] Uploading {bname} ...")
    job_id = uploader.upload_batch(driver, bname)

    if job_id:
        log.info(f"  [OK] job_id = {job_id}")
        batch_state = sm.get_all()
        for pid, rec in batch_state.items():
            if rec.get("batch") == bname:
                sm.mark_uploaded(pid, job_id, TODAY)
                nc.mark_uploaded_in_notion(pid, TODAY)
        ok += 1
    else:
        log.error(f"  [FAIL] {bname} — no job ID")
        batch_state = sm.get_all()
        for pid, rec in batch_state.items():
            if rec.get("batch") == bname:
                sm.mark_failed(pid, "retry_no_job_id")
        fail += 1
        # Only delay on failure to let server recover
        if i < len(all_batches) and args.delay > 0:
            log.info(f"  Waiting {args.delay}s after failure ...")
            time.sleep(args.delay)

_stop_heartbeat.set()
driver.quit()
log.info(f"\nDone. OK={ok}  Failed={fail}  Log={log_path}")
