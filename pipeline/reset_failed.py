"""Reset videos that failed due to upload_no_job_id back to 'downloaded' status."""
import json, shutil
from datetime import datetime

src = "state.json"
with open(src, encoding="utf-8") as f:
    state = json.load(f)

# Count current statuses
counts = {}
for pid, rec in state.items():
    s = rec.get("pipeline_status", "unknown")
    counts[s] = counts.get(s, 0) + 1
print("BEFORE:")
for s, n in sorted(counts.items()):
    print(f"  {s}: {n}")

# Reset failed entries that have a local_file (i.e., were downloaded successfully)
reset_count = 0
for pid, rec in state.items():
    if rec.get("pipeline_status") == "failed":
        local_file = rec.get("local_file", "")
        if local_file:
            rec["pipeline_status"] = "downloaded"
            # Clear batch assignment so it gets re-batched
            if "batch" in rec:
                del rec["batch"]
            reset_count += 1

print(f"\nReset {reset_count} failed entries back to 'downloaded'")

# Backup and save
bak = f"state.json.bak_{datetime.now().strftime('%H%M%S')}"
shutil.copy(src, bak)
print(f"Backup: {bak}")

with open(src, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2)

# Count after
counts2 = {}
for pid, rec in state.items():
    s = rec.get("pipeline_status", "unknown")
    counts2[s] = counts2.get(s, 0) + 1
print("\nAFTER:")
for s, n in sorted(counts2.items()):
    print(f"  {s}: {n}")
