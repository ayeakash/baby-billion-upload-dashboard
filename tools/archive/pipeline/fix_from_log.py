"""
Fix state.json using confirmed Notion page IDs from the pipeline log.
These videos were successfully uploaded to both admin + Notion but got
marked 'failed' when a later batch upload hit a DNS error.
"""
import json, shutil
from datetime import datetime

STATE = "state.json"
CONFIRMED_FILE = "notion_confirmed_pids.txt"

# Load confirmed page IDs from log extraction
with open(CONFIRMED_FILE, encoding="utf-8") as f:
    confirmed_pids = set(line.strip() for line in f if line.strip())

print(f"Confirmed page IDs from log: {len(confirmed_pids)}")

# Back up
bak = f"state.json.bak_{datetime.now().strftime('%H%M%S')}"
shutil.copy(STATE, bak)
print(f"Backed up to {bak}")

with open(STATE, encoding="utf-8") as f:
    state = json.load(f)

fixed = 0
already_ok = 0
reset_pending = 0

for pid, rec in state.items():
    status = rec.get("pipeline_status", "")
    
    if status == "failed":
        if pid in confirmed_pids:
            # Confirmed uploaded in Notion — restore
            rec["pipeline_status"] = "uploaded"
            rec["upload_date"] = "2026-04-23"
            if "fail_reason" in rec:
                del rec["fail_reason"]
            fixed += 1
            print(f"  [FIX] {rec.get('video_name', pid)}: restored to 'uploaded'")
        else:
            # Not confirmed — reset to pending for retry
            rec["pipeline_status"] = "pending"
            if "fail_reason" in rec:
                del rec["fail_reason"]
            reset_pending += 1
            print(f"  [RESET] {rec.get('video_name', pid)}: reset to 'pending'")
    elif pid in confirmed_pids:
        already_ok += 1

with open(STATE, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"\nDone:")
print(f"  {fixed} restored to 'uploaded'")
print(f"  {reset_pending} reset to 'pending' for retry")
print(f"  {already_ok} were already OK")

# Final summary
counts = {}
for pid, rec in state.items():
    s = rec.get("pipeline_status", "unknown")
    counts[s] = counts.get(s, 0) + 1
print("\nFinal state:")
for s, n in sorted(counts.items()):
    print(f"  {s}: {n}")
