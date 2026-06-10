"""
Check the actual Notion status of the 29 'pending' videos in state.json.
If they're already marked Upload=Yes in Notion, update state.json to match.
"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))

import requests
from config import NOTION_TOKEN, PROP_UPLOAD, PROP_UPLOAD_DATE, PROP_VIDEO_NAME

NOTION_VERSION = "2022-06-28"
BASE = "https://api.notion.com/v1"

def headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

def get_upload_status(page_id):
    """Check a single page's Upload status in Notion."""
    url = f"{BASE}/pages/{page_id}"
    resp = requests.get(url, headers=headers(), timeout=15)
    if resp.status_code != 200:
        return None, None, resp.status_code
    
    props = resp.json().get("properties", {})
    
    # Extract Upload value
    upload_prop = props.get(PROP_UPLOAD, {})
    upload_type = upload_prop.get("type", "")
    if upload_type == "checkbox":
        upload_val = "Yes" if upload_prop.get("checkbox", False) else "No"
    elif upload_type == "select":
        sel = upload_prop.get("select")
        upload_val = sel["name"] if sel else "No"
    else:
        upload_val = "???"
    
    # Extract Upload Date
    date_prop = props.get(PROP_UPLOAD_DATE, {})
    date_val = ""
    if date_prop.get("type") == "date" and date_prop.get("date"):
        date_val = date_prop["date"].get("start", "")
    
    return upload_val, date_val, 200

# Load state
with open("state.json", encoding="utf-8") as f:
    state = json.load(f)

pending = [(pid, rec) for pid, rec in state.items() if rec.get("pipeline_status") == "pending"]
print(f"Checking {len(pending)} pending videos against Notion API...\n")

already_uploaded = []
truly_pending = []

for i, (pid, rec) in enumerate(pending, 1):
    name = rec.get("video_name", "???")
    upload_val, date_val, status_code = get_upload_status(pid)
    
    if status_code != 200:
        print(f"  {i:>2}. {name:<50} API error: {status_code}")
        truly_pending.append(pid)
        continue
    
    marker = "[DONE]" if upload_val == "Yes" else "[NOT DONE]"
    print(f"  {i:>2}. {name:<50} Upload={upload_val:<6} Date={date_val or 'none'} {marker}")
    
    if upload_val == "Yes":
        already_uploaded.append((pid, date_val))
    else:
        truly_pending.append(pid)

print(f"\n=== SUMMARY ===")
print(f"  Already uploaded in Notion: {len(already_uploaded)}")
print(f"  Truly pending (Upload=No): {len(truly_pending)}")

if already_uploaded:
    print(f"\nThese {len(already_uploaded)} should be fixed in state.json to 'uploaded'.")
