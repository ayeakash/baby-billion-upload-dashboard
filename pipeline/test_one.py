"""
test_one.py -- Run the full pipeline on just the FIRST ready-to-upload video.
Usage: python test_one.py
"""

import os, sys, logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

import notion_client as nc
import downloader
import compressor
import batcher
import zipper
import uploader
import state_manager as sm
from datetime import date

log.info("=" * 55)
log.info("  SINGLE-VIDEO TEST RUN")
log.info("=" * 55)

# ── 1. Fetch one video from Notion ─────────────────────────────────────────────
log.info("\n[1] Querying Notion ...")
if not nc.validate_connection():
    sys.exit(1)

videos = nc.query_ready_to_upload()
if not videos:
    log.error("No ready-to-upload videos found in Notion.")
    sys.exit(1)

v = videos[0]
log.info(f"\nTesting with: {v['video_name']}")
log.info(f"  Category  : {v['category']}")
log.info(f"  Age Group : {v['age_group']}")
log.info(f"  Drive Link: {v['drive_link'][:80]}")

sm.upsert(v["page_id"],
          video_name=v["video_name"],
          age_group=v["age_group"],
          category=v["category"],
          drive_link=v["drive_link"],
          pipeline_status="pending")

# ── 2. Download ────────────────────────────────────────────────────────────────
log.info("\n[2] Downloading ...")
local_file = downloader.download_video(v["page_id"], v["video_name"], v["drive_link"])
if not local_file:
    log.error("Download failed -- aborting test.")
    sys.exit(1)

sm.mark_downloaded(v["page_id"], local_file)
v["local_file"] = local_file
log.info(f"  Downloaded: {local_file}")

# ── 3. Compress ────────────────────────────────────────────────────────────────
log.info("\n[3] Compressing ...")
compressor.compress(v["page_id"], v["video_name"], v["local_file"])

# ── 4. Batch + CSV ─────────────────────────────────────────────────────────────
log.info("\n[4] Batching ...")
batch_names = batcher.run([v])
if not batch_names:
    log.warning("  Already batched or nothing to batch.")
    rec = sm.get(v["page_id"])
    batch_names = [rec["batch"]] if rec and rec.get("batch") else []

if not batch_names:
    log.error("No batch created -- aborting test.")
    sys.exit(1)

log.info(f"  Batch: {batch_names[0]}")

# ── 5. Zip ─────────────────────────────────────────────────────────────────────
log.info("\n[5] Zipping ...")
zipped = zipper.zip_all(batch_names)
if not zipped:
    log.error("Zip failed -- aborting test.")
    sys.exit(1)

log.info(f"  ZIP: {list(zipped.values())[0]}")

# ── 6. Upload ──────────────────────────────────────────────────────────────────
log.info("\n[6] Uploading to admin.babybillion.in ...")
job_map = uploader.run_all(list(zipped.keys()), headless=False)

# ── 7. Track + Notion write-back ───────────────────────────────────────────────
log.info("\n[7] Writing back to Notion ...")
today = date.today().isoformat()

for batch_name, job_id in job_map.items():
    if job_id:
        sm.mark_uploaded(v["page_id"], job_id, today)
        success = nc.mark_uploaded_in_notion(v["page_id"], today)
        log.info(f"  Notion updated: {success}  | job_id: {job_id}")
    else:
        sm.mark_failed(v["page_id"], "upload_no_job_id")
        log.error("  Upload returned no job_id -- Notion NOT updated.")

# ── Summary ────────────────────────────────────────────────────────────────────
log.info("\n" + "=" * 55)
log.info("  TEST COMPLETE")
log.info("=" * 55)
log.info(f"  Video     : {v['video_name']}")
log.info(f"  State     : {sm.get(v['page_id']).get('pipeline_status')}")
log.info(f"  Job ID    : {sm.get(v['page_id']).get('job_id', 'none')}")
log.info(f"  Notion    : {'updated' if job_map and list(job_map.values())[0] else 'NOT updated'}")
