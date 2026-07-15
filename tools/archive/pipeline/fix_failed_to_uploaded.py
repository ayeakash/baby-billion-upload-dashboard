"""
Fix state.json: reset videos that were marked 'failed' with reason 'upload_no_job_id'
back to 'uploaded' if they were already confirmed uploaded in Notion.

The pipeline hit a DNS error (ERR_NAME_NOT_RESOLVED) during a batch upload,
which caused videos that had ALREADY been uploaded & confirmed in Notion to get
re-marked as failed because they shared the same Batch_52 name.
"""
import json, shutil
from datetime import datetime

STATE = "state.json"

# Back up first
bak = f"state.json.bak_{datetime.now().strftime('%H%M%S')}"
shutil.copy(STATE, bak)
print(f"Backed up to {bak}")

with open(STATE, encoding="utf-8") as f:
    state = json.load(f)

fixed = 0
still_failed = 0

for pid, rec in state.items():
    status = rec.get("pipeline_status", "")
    reason = rec.get("fail_reason", "")
    
    if status == "failed" and reason == "upload_no_job_id":
        # Check if Notion was already updated (upload_date set means it was confirmed)
        if rec.get("upload_date"):
            # Already confirmed in Notion — restore to uploaded
            rec["pipeline_status"] = "uploaded"
            del rec["fail_reason"]
            fixed += 1
            print(f"  [FIX] {rec.get('video_name', pid)}: restored to 'uploaded' (upload_date={rec['upload_date']})")
        else:
            # Genuinely failed — reset to 'downloaded' so pipeline can retry
            local_file = rec.get("local_file", "")
            rec["pipeline_status"] = "pending"
            if "fail_reason" in rec:
                del rec["fail_reason"]
            still_failed += 1
            print(f"  [RESET] {rec.get('video_name', pid)}: reset to 'pending' for retry")

with open(STATE, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"\nDone: {fixed} restored to 'uploaded', {still_failed} reset to 'pending'")

# Final summary
counts = {}
for pid, rec in state.items():
    s = rec.get("pipeline_status", "unknown")
    counts[s] = counts.get(s, 0) + 1
print("\nFinal state:")
for s, n in sorted(counts.items()):
    print(f"  {s}: {n}")
