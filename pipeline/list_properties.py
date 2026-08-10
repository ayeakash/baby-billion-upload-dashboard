"""List all property names in the Notion database."""

import requests
from config import NOTION_TOKEN, NOTION_DATABASE_ID

NOTION_VERSION = "2025-09-03"
BASE = "https://api.notion.com/v1"

def _headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

url = f"{BASE}/databases/{NOTION_DATABASE_ID}"
resp = requests.get(url, headers=_headers(), timeout=15)

if resp.status_code == 200:
    db = resp.json()

    # Try data sources first
    data_sources = db.get("data_sources", [])
    if data_sources:
        print(f"Database has {len(data_sources)} data source(s)")
        for ds in data_sources:
            ds_id = ds.get("id")
            print(f"\nData source: {ds_id}")
            ds_url = f"{BASE}/data_sources/{ds_id}"
            ds_resp = requests.get(ds_url, headers=_headers(), timeout=15)
            if ds_resp.status_code == 200:
                ds_data = ds_resp.json()
                props = ds_data.get("properties", {})
                print(f"Properties ({len(props)} total):\n")
                for name in sorted(props.keys()):
                    prop_type = props[name].get("type", "unknown")
                    print(f"  {name:<40} ({prop_type})")
    else:
        # Fall back to database properties
        props = db.get("properties", {})
        print(f"Database: {db.get('title', [{}])[0].get('plain_text', 'Unknown')}")
        print(f"\nProperties ({len(props)} total):\n")
        for name in sorted(props.keys()):
            prop_type = props[name].get("type", "unknown")
            print(f"  {name:<40} ({prop_type})")
else:
    print(f"Error: {resp.status_code}")
    print(resp.text)
