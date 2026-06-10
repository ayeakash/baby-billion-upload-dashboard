"""
Re-fix the 43 wrongly marked videos in Notion:
  - Upload = "No"
  - Upload Date = cleared
  - Status = "Ready to Upload"
"""
import json, requests, time
from config import (
    NOTION_TOKEN,
    PROP_UPLOAD, PROP_UPLOAD_DATE, PROP_STATUS,
    UPLOAD_NO, STATUS_READY,
)

NOTION_VERSION = "2022-06-28"
BASE = "https://api.notion.com/v1"

def headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

state = json.load(open("state.json", "r", encoding="utf-8"))

# Find non-uploaded entries
non_uploaded = [
    (pid, rec) for pid, rec in state.items()
    if rec.get("pipeline_status") != "uploaded"
]
print(f"Total non-uploaded in state.json: {len(non_uploaded)}")
print(f"Checking each against Notion API...\n")

to_fix = []
for pid, rec in non_uploaded:
    try:
        r = requests.get(f"{BASE}/pages/{pid}", headers=headers(), timeout=15)
        if r.status_code != 200:
            continue
        props = r.json().get("properties", {})

        # Check if Upload is marked as done
        upload_prop = props.get(PROP_UPLOAD, {})
        t = upload_prop.get("type", "")
        if t == "checkbox":
            is_uploaded = upload_prop.get("checkbox", False)
        elif t == "select":
            sel = upload_prop.get("select")
            is_uploaded = (sel["name"].lower() == "yes") if sel else False
        else:
            is_uploaded = False

        # Check if Status is NOT "Ready to Upload"
        status_prop = props.get(PROP_STATUS, {})
        status_val = ""
        st = status_prop.get("type", "")
        if st == "select":
            sel = status_prop.get("select")
            status_val = sel["name"] if sel else ""

        needs_fix = is_uploaded or (status_val != STATUS_READY)
        if needs_fix:
            to_fix.append((pid, rec, status_val, is_uploaded))
            name = rec.get("video_name", "?")
            ps = rec.get("pipeline_status", "?")
            print(f"  [WILL FIX] {name:50s} state={ps:15s} Notion: Upload={'Yes' if is_uploaded else 'No'}, Status='{status_val}'")
    except Exception as e:
        print(f"  [ERR] {pid}: {e}")
    time.sleep(0.35)

print(f"\n{'='*60}")
print(f"Found {len(to_fix)} videos to fix in Notion.")

if not to_fix:
    print("Nothing to fix!")
    exit(0)

# Fix each: Upload=No, Upload Date=None, Status=Ready to Upload
fixed = 0
failed = 0
for pid, rec, _, _ in to_fix:
    name = rec.get("video_name", "?")
    for prop_type in ("select", "checkbox"):
        if prop_type == "select":
            patch = {"properties": {
                PROP_UPLOAD: {"select": {"name": UPLOAD_NO}},
                PROP_UPLOAD_DATE: {"date": None},
                PROP_STATUS: {"select": {"name": STATUS_READY}},
            }}
        else:
            patch = {"properties": {
                PROP_UPLOAD: {"checkbox": False},
                PROP_UPLOAD_DATE: {"date": None},
                PROP_STATUS: {"select": {"name": STATUS_READY}},
            }}

        r = requests.patch(f"{BASE}/pages/{pid}", headers=headers(), json=patch, timeout=15)
        if r.status_code == 200:
            fixed += 1
            print(f"  [FIXED] {name}")
            break
        elif r.status_code == 400:
            continue
        else:
            print(f"  [FAIL] {name}: HTTP {r.status_code} {r.text[:200]}")
            failed += 1
            break
    time.sleep(0.35)

print(f"\n{'='*60}")
print(f"Fixed: {fixed}")
print(f"Failed: {failed}")
