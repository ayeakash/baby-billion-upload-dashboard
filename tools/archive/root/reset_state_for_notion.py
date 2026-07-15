"""Reset state.json entries for the 50 videos currently in Notion 'Ready to Upload'.
These were marked 'uploaded' in state.json from prior runs but many actually
failed on the CMS and are still waiting in Notion.
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'pipeline'))

import notion_client as nc

# Get the current Notion ready-to-upload videos  
videos = nc.query_ready_to_upload()
print(f"Found {len(videos)} videos in Notion 'Ready to Upload'")

# Load state.json
state_path = os.path.join(os.path.dirname(__file__), "state.json")
state = json.load(open(state_path, "r", encoding="utf-8"))
print(f"State.json has {len(state)} entries")

# For each video, find and reset its state.json entry
reset_count = 0
for v in videos:
    page_id = v["page_id"]
    video_name = v["video_name"]
    
    # The state key format includes page_id with or without dashes + lang suffix
    keys_to_reset = []
    for k, rec in state.items():
        if not isinstance(rec, dict):
            continue
        # Match by page_id (could be with dashes or without)
        pid_clean = page_id.replace("-", "")
        if pid_clean in k.replace("-", ""):
            if rec.get("pipeline_status") in ("uploaded", "downloaded", "batched", "zipped", "failed"):
                keys_to_reset.append(k)
    
    for k in keys_to_reset:
        old_status = state[k].get("pipeline_status", "?")
        state[k]["pipeline_status"] = "pending"
        state[k].pop("batch", None)
        state[k].pop("local_file", None)
        reset_count += 1
        if reset_count <= 20:
            short_name = video_name[:50]
            print(f"  RESET {k[:40]:40s} {old_status:12s} -> pending | {short_name}")

if reset_count > 20:
    print(f"  ... and {reset_count - 20} more")

# Save
json.dump(state, open(state_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print(f"\nDone! Reset {reset_count} state.json entries to 'pending'")
