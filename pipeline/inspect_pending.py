"""Inspect all pending videos to identify what's blocking them."""
import json

with open("state.json", encoding="utf-8") as f:
    state = json.load(f)

pending = [(pid, rec) for pid, rec in state.items() if rec.get("pipeline_status") == "pending"]
print(f"Total pending: {len(pending)}\n")

no_link = []
has_link = []

for pid, rec in pending:
    name = rec.get("video_name", "???")
    link = rec.get("drive_link", "")
    cat = rec.get("category", "???")
    age = rec.get("age_group", "???")
    
    if not link or link.strip() == "":
        no_link.append((name, cat, age, pid))
    else:
        has_link.append((name, link, cat, age, pid))

print(f"=== NO DRIVE LINK ({len(no_link)}) ===")
for i, (name, cat, age, pid) in enumerate(no_link, 1):
    print(f"  {i:>3}. {name:<55} cat={cat:<25} age={age}")

print(f"\n=== HAS DRIVE LINK ({len(has_link)}) ===")
for i, (name, link, cat, age, pid) in enumerate(has_link, 1):
    print(f"  {i:>3}. {name:<55} link={link[:70]}")
    print(f"       cat={cat:<25} age={age}")
