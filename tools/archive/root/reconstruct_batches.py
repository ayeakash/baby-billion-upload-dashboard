"""
Mark the right batches as uploaded based on upload_history.jsonl.
Reconstructs batches.json entries for successfully uploaded batches.
"""
import json, os, sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))
import state_manager as sm

BATCHES_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batches.json")
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upload_history.jsonl")

# Read upload history
history = []
with open(HISTORY_FILE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            history.append(json.loads(line))

# Group by batch_name, take the LAST status for each (most recent)
batch_results = {}
for entry in history:
    bn = entry.get("batch_name", "")
    job_id = entry.get("job_id", "")
    status = entry.get("status", "")
    video_name = entry.get("video_name", "")
    
    if bn not in batch_results:
        batch_results[bn] = {"job_id": job_id, "status": status, "videos": []}
    
    # Update with latest job_id/status if it has one
    if job_id:
        batch_results[bn]["job_id"] = job_id
    if status in ("submitted",):
        batch_results[bn]["status"] = status
    
    if video_name:
        batch_results[bn]["videos"].append(video_name)

# Load existing batches.json
if os.path.isfile(BATCHES_JSON):
    with open(BATCHES_JSON, "r", encoding="utf-8") as f:
        batches = json.load(f)
else:
    batches = {}

# CMS results from screenshot for cross-reference
cms_completed = {
    "b655a33e-ef6b-456e-9997-be36355b672a": "COMPLETED",
    "21793618-5036-4ce2-a3cb-1e858881d785": "COMPLETED",
    "92609673-1792-49c0-b3eb-c1780c5f39ef": "COMPLETED",
    "f7eb5ff9-d6fc-474f-a001-f811d42b2479": "COMPLETED",
    "30f86cd9-e4ea-433e-9548-48eaec163109": "COMPLETED",
    "9df9eaa5-b47c-4ded-b2dd-bc42749ed5e0": "COMPLETED",
    "1a05f317-db21-4aac-aaac-2524a4e39ca5": "COMPLETED",
    # FAILED ones
    "c28fb891-f5de-4dad-9122-5308d1c90322": "FAILED",
    "d04d7af8-413c-4a7a-9699-851bc4a00a21": "FAILED",
    "38e82f61-4055-4ef4-a827-eff73c228488": "FAILED",
}

uploaded_count = 0
failed_count = 0

for bn, data in sorted(batch_results.items()):
    job_id = data["job_id"]
    status = data["status"]
    videos = list(set(data["videos"]))  # deduplicate
    
    # Check against CMS
    cms_status = cms_completed.get(job_id, "UNKNOWN")
    
    if cms_status == "COMPLETED" and job_id:
        # Mark as uploaded
        batches[bn] = {
            "status": "pending_second_review",
            "created_at": date.today().isoformat(),
            "upload_job_id": job_id,
            "upload_failed": False,
            "videos": [{"video_name": v, "page_id": ""} for v in videos],
            "batch_size_bytes": 0,
        }
        uploaded_count += 1
        print(f"  UPLOADED: {bn} -> {job_id[:16]}... ({len(videos)} videos: {', '.join(videos[:3])})")
        
        # Mark in state.json
        for v in videos:
            try:
                sm.upsert(v, pipeline_status="uploaded", batch=bn)
            except Exception:
                pass
                
    elif cms_status == "FAILED" or (not job_id and status == "upload_failed"):
        # Mark as failed
        batches[bn] = {
            "status": "pending_first_review",
            "created_at": date.today().isoformat(),
            "upload_job_id": job_id or "",
            "upload_failed": True,
            "fail_reason": f"CMS rejected upload" + (f" (Job: {job_id[:12]}...)" if job_id else ""),
            "videos": [{"video_name": v, "page_id": ""} for v in videos],
            "batch_size_bytes": 0,
        }
        failed_count += 1
        # Don't print every failed one, there are many
    else:
        # approval_failed with COMPLETED CMS status means it actually went through
        if job_id and cms_status == "COMPLETED":
            batches[bn] = {
                "status": "pending_second_review",
                "created_at": date.today().isoformat(),
                "upload_job_id": job_id,
                "upload_failed": False,
                "videos": [{"video_name": v, "page_id": ""} for v in videos],
                "batch_size_bytes": 0,
            }
            uploaded_count += 1
            print(f"  UPLOADED (was approval_failed but CMS says COMPLETED): {bn} -> {job_id[:16]}...")

with open(BATCHES_JSON, "w", encoding="utf-8") as f:
    json.dump(batches, f, indent=2, ensure_ascii=False)

print(f"\nDone! {uploaded_count} marked uploaded, {failed_count} marked failed.")
print(f"Total batches in batches.json: {len(batches)}")
