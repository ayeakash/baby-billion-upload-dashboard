"""
run_batch_upload.py — Upload created batches to the admin CMS portal via Selenium.
Target batches: Batch_07, Batch_08, Batch_09
"""

import os
import sys
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(BASE_DIR, "pipeline")
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import uploader
import state_manager as sm

BATCHES_JSON = os.path.join(BASE_DIR, "batches.json")
STATE_JSON = os.path.join(BASE_DIR, "state.json")

BATCHES_TO_UPLOAD = ["Batch_07", "Batch_08", "Batch_09"]


def update_records_after_batch_result(batch_name: str, result: dict):
    """Callback triggered after each batch completes upload."""
    print(f"\n[CALLBACK] Processing upload result for {batch_name}: {result}")
    status = result.get("status", "upload_failed")
    job_id = result.get("job_id")
    upload_date = datetime.now().strftime("%Y-%m-%d")

    # Load batches.json
    batches_data = {}
    if os.path.isfile(BATCHES_JSON):
        try:
            with open(BATCHES_JSON, "r", encoding="utf-8") as f:
                batches_data = json.load(f)
        except Exception as e:
            print(f"Error loading batches.json: {e}")

    if batch_name in batches_data:
        b = batches_data[batch_name]
        if status == "submitted":
            b["upload_job_id"] = job_id
            b["upload_date"] = upload_date
            b["upload_completed"] = True
            b["upload_failed"] = False
            b["status"] = "pending_first_review"
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
        else:
            b["upload_failed"] = True
            b["fail_reason"] = "Upload failed on admin site"
            for v in b["videos"]:
                v["pipeline_status"] = "upload_failed"

        tmp_bj = BATCHES_JSON + ".tmp"
        with open(tmp_bj, "w", encoding="utf-8") as f:
            json.dump(batches_data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_bj, BATCHES_JSON)

    # Load state.json
    state_data = {}
    if os.path.isfile(STATE_JSON):
        try:
            with open(STATE_JSON, "r", encoding="utf-8") as f:
                state_data = json.load(f)
        except Exception as e:
            print(f"Error loading state.json: {e}")

    if batch_name in batches_data:
        for v in batches_data[batch_name].get("videos", []):
            sk = v.get("page_id", "")
            if sk and sk in state_data:
                if status == "submitted":
                    state_data[sk]["pipeline_status"] = "uploaded"
                    state_data[sk]["job_id"] = job_id
                    state_data[sk]["upload_date"] = upload_date
                elif status in ("upload_failed", "approval_failed"):
                    state_data[sk]["pipeline_status"] = status
                state_data[sk]["updated_at"] = datetime.now().isoformat()

        tmp_sj = STATE_JSON + ".tmp"
        with open(tmp_sj, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_sj, STATE_JSON)


def main():
    print(f"Starting upload for batches: {', '.join(BATCHES_TO_UPLOAD)}...")
    results = uploader.run_all_and_submit(
        batch_names=BATCHES_TO_UPLOAD,
        headless=False,
        on_result=update_records_after_batch_result
    )

    print("\n============================================================")
    print("  UPLOAD SUMMARY REPORT")
    print("============================================================")
    for bname, res in results.items():
        status = res.get("status")
        job_id = res.get("job_id")
        verified = res.get("verified", False)
        print(f"  {bname}: Status='{status}', Job ID='{job_id}', Verified={verified}")
    print("============================================================\n")


if __name__ == "__main__":
    main()
