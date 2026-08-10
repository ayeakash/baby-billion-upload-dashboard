"""
recreate_stories_csv.py -- Recreate Stories_Entertainment CSV from Notion.
"""

import csv
import requests
import logging
from pathlib import Path
from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID,
    PROP_VIDEO_NAME, PROP_AGE_GROUP, PROP_CATEGORY, PROP_LANGUAGE,
    ADMIN_CSV_HEADER, BATCHES_DIR,
)

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)

NOTION_VERSION = "2025-09-03"
BASE = "https://api.notion.com/v1"

STORY_CATEGORIES = [
    "Krishna", "Aladdin", "English Stories", "Tenali", "Panchatantra",
    "Mishka And Momo", "Hindi Stories", "Sindbad", "Hanuman"
]


def _headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _prop_value(properties: dict, name: str) -> str:
    """Extract property value."""
    prop = properties.get(name)
    if prop is None:
        return ""
    t = prop.get("type", "")
    if t == "title":
        parts = prop.get("title", [])
        return "".join(p.get("plain_text", "") for p in parts).strip()
    if t == "rich_text":
        parts = prop.get("rich_text", [])
        return "".join(p.get("plain_text", "") for p in parts).strip()
    if t == "select":
        sel = prop.get("select")
        return sel["name"] if sel else ""
    if t == "multi_select":
        return ", ".join(o["name"] for o in prop.get("multi_select", []))
    if t == "date":
        d = prop.get("date")
        return d["start"] if d else ""
    if t == "url":
        return prop.get("url") or ""
    return ""


def _resolve_data_source_id() -> str:
    """Resolve data source ID."""
    url = f"{BASE}/databases/{NOTION_DATABASE_ID}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 200:
            db = resp.json()
            data_sources = db.get("data_sources", [])
            if data_sources:
                return data_sources[0].get("id", NOTION_DATABASE_ID)
    except Exception as e:
        log.warning(f"Could not resolve data source: {e}")
    return NOTION_DATABASE_ID


def _query_url() -> str:
    """Return query URL."""
    ds_id = _resolve_data_source_id()
    return f"{BASE}/data_sources/{ds_id}/query"


def query_story_videos() -> list[dict]:
    """Query Notion for all story category videos."""
    log.info("Querying Notion for story videos...")

    url = _query_url()
    results = []
    seen_pages = set()

    # Build filter for story categories
    or_filters = [
        {
            "property": PROP_CATEGORY,
            "multi_select": {"contains": cat}
        }
        for cat in STORY_CATEGORIES
    ]

    cursor = None
    while True:
        payload = {
            "filter": {"or": or_filters},
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor

        try:
            resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
            if resp.status_code != 200:
                log.error(f"Query failed: {resp.status_code}")
                break
            data = resp.json()
        except Exception as e:
            log.error(f"Request error: {e}")
            break

        for page in data.get("results", []):
            page_id = page["id"]
            if page_id in seen_pages:
                continue
            seen_pages.add(page_id)

            props = page["properties"]
            video_name = _prop_value(props, PROP_VIDEO_NAME).strip()
            age_group = _prop_value(props, PROP_AGE_GROUP).strip()
            category = _prop_value(props, PROP_CATEGORY).strip()
            language = _prop_value(props, PROP_LANGUAGE).strip()

            if not video_name:
                continue

            results.append({
                "video_name": video_name,
                "categories_name": "Entertainment",  # Override for stories
                "age_groups": age_group,
                "channel_name": "BabyBillion_Education",
                "tags": "",
                "playlist_name": "",  # Empty as requested
                "content_formats": "",
                "content_types": "Original",
                "language": language,
            })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    log.info(f"Found {len(results)} unique videos")
    return results


def create_csv(videos: list[dict]) -> Path:
    """Create Stories_Entertainment CSV."""
    csv_file = Path(BATCHES_DIR) / "Stories_Entertainment.csv"

    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=ADMIN_CSV_HEADER)
        writer.writeheader()
        writer.writerows(videos)

    log.info(f"Created: {csv_file.name} with {len(videos)} videos")
    return csv_file


def main():
    """Main entry point."""
    log.info("=" * 70)
    log.info("Recreate Stories_Entertainment CSV")
    log.info("=" * 70 + "\n")

    videos = query_story_videos()

    if not videos:
        log.error("No videos found")
        return False

    create_csv(videos)
    return True


if __name__ == "__main__":
    main()
