"""Extract CMS Batch ID -> Dashboard Batch Name mapping with status."""
import json, io, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

history = [json.loads(l) for l in open('upload_history.jsonl', encoding='utf-8')]

# Group by (batch_name, job_id) -> latest status + videos
mapping = {}
for e in history:
    bn = e.get("batch_name", "")
    jid = e.get("job_id", "")
    status = e.get("status", "")
    vn = e.get("video_name", "")
    
    key = (bn, jid)
    if key not in mapping:
        mapping[key] = {"status": status, "videos": set()}
    mapping[key]["videos"].add(vn)
    # Keep the most "positive" status
    if status in ("submitted",):
        mapping[key]["status"] = status

# Print grouped by job_id
seen_jids = {}
for (bn, jid), data in sorted(mapping.items()):
    if not jid:
        continue
    if jid not in seen_jids:
        seen_jids[jid] = []
    seen_jids[jid].append((bn, data))

print(f"{'CMS Batch ID':<40} {'Dashboard':<14} {'Status':<18} {'Videos'}")
print("=" * 120)
for jid in sorted(seen_jids.keys()):
    entries = seen_jids[jid]
    for bn, data in entries:
        vids = ", ".join(sorted(v[:45] for v in data["videos"]))
        print(f"{jid:<40} {bn:<14} {data['status']:<18} {vids[:60]}")
