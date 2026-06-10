"""
mark_manual_upload.py
Mark a manually uploaded batch as done in state.json + Notion.

Usage:
    python mark_manual_upload.py <batch_name> <job_id>
Example:
    python mark_manual_upload.py Batch_03 3bb8cc2c-1c50-49f2-b754-4965d93a356a
"""
import os, sys, logging
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

import state_manager as sm
import notion_client as nc

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

batch_name = sys.argv[1]   # e.g. Batch_03
job_id     = sys.argv[2]   # e.g. 3bb8cc2c-1c50-49f2-b754-4965d93a356a
today      = date.today().isoformat()

# Find all page_ids that belong to this batch
state = sm.get_all()
matched = [(pid, rec) for pid, rec in state.items() if rec.get("batch") == batch_name]

if not matched:
    log.error(f"No entries found in state.json for batch '{batch_name}'")
    log.info("Current state entries:")
    for pid, rec in state.items():
        log.info(f"  {rec.get('video_name')} | batch={rec.get('batch')} | status={rec.get('pipeline_status')}")
    sys.exit(1)

log.info(f"Marking {len(matched)} video(s) in {batch_name} as uploaded (job_id={job_id})")

notion_ok = 0
notion_fail = 0
for pid, rec in matched:
    # Update state.json
    sm.mark_uploaded(pid, job_id, today)
    log.info(f"  [STATE] {rec.get('video_name')} -> uploaded")

    # Update Notion
    success = nc.mark_uploaded_in_notion(pid, today)
    if success:
        notion_ok += 1
        log.info(f"  [NOTION] {rec.get('video_name')} -> updated OK")
    else:
        notion_fail += 1
        log.warning(f"  [NOTION] {rec.get('video_name')} -> FAILED (state.json still updated)")

log.info(f"\nDone. Notion updated: {notion_ok}, failed: {notion_fail}")
