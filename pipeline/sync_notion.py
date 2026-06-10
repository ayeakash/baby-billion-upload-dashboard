"""
sync_notion.py -- Reconcile state.json -> Notion for uploaded videos.

Finds all videos marked 'uploaded' in state.json but not yet marked
in Notion, and updates them. Safe to run at any time.

Usage:
    python sync_notion.py          # dry-run (show what would be fixed)
    python sync_notion.py --fix    # actually update Notion
"""

import json
import sys
import time
import requests
from datetime import date
from config import (
    NOTION_TOKEN, PROP_UPLOAD, PROP_UPLOAD_DATE, PROP_STATUS,
    UPLOAD_YES, STATE_FILE,
)

NOTION_VERSION = "2022-06-28"
BASE = "https://api.notion.com/v1"
TODAY = date.today().isoformat()

def headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

def main():
    fix_mode = "--fix" in sys.argv

    state = json.load(open(STATE_FILE, "r", encoding="utf-8"))

    # Find all uploaded videos
    uploaded = [
        (pid, rec) for pid, rec in state.items()
        if isinstance(rec, dict) and rec.get("pipeline_status") == "uploaded"
    ]
    print(f"Total 'uploaded' in state.json: {len(uploaded)}")
    print(f"Checking each against Notion API...\n")

    out_of_sync = []
    checked = 0
    for pid, rec in uploaded:
        checked += 1
        name = rec.get("video_name", "?")
        try:
            r = requests.get(f"{BASE}/pages/{pid}", headers=headers(), timeout=15)
            if r.status_code != 200:
                print(f"  [SKIP] {name}: HTTP {r.status_code}")
                continue
            props = r.json().get("properties", {})

            # Check Upload property
            upload_prop = props.get(PROP_UPLOAD, {})
            t = upload_prop.get("type", "")
            if t == "checkbox":
                is_uploaded = upload_prop.get("checkbox", False)
            elif t == "select":
                sel = upload_prop.get("select")
                is_uploaded = (sel["name"].lower() == "yes") if sel else False
            else:
                is_uploaded = False

            if not is_uploaded:
                out_of_sync.append((pid, rec))
                print(f"  [NEEDS SYNC] {name}")

        except Exception as e:
            print(f"  [ERR] {name}: {e}")

        if checked % 50 == 0:
            print(f"  ... checked {checked}/{len(uploaded)}")
        time.sleep(0.35)

    print(f"\n{'='*60}")
    print(f"Checked: {checked}")
    print(f"Out of sync: {len(out_of_sync)}")

    if not out_of_sync:
        print("Everything is in sync!")
        return

    if not fix_mode:
        print("\nRun with --fix to update Notion for these videos.")
        return

    # Fix each
    print(f"\nFixing {len(out_of_sync)} videos in Notion...\n")
    fixed = 0
    failed = 0
    for pid, rec in out_of_sync:
        name = rec.get("video_name", "?")
        upload_date = rec.get("upload_date", TODAY)

        for prop_type in ("select", "checkbox"):
            if prop_type == "select":
                patch = {"properties": {
                    PROP_UPLOAD: {"select": {"name": UPLOAD_YES}},
                    PROP_UPLOAD_DATE: {"date": {"start": upload_date}},
                }}
            else:
                patch = {"properties": {
                    PROP_UPLOAD: {"checkbox": True},
                    PROP_UPLOAD_DATE: {"date": {"start": upload_date}},
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


if __name__ == "__main__":
    main()
