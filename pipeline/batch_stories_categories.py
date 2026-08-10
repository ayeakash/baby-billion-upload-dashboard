"""
batch_stories_categories.py -- Batch videos from story categories to CSV.

Story categories:
  - Krishna, Aladdin, English Stories, Tenali, Panchatantra
  - Mishka And Momo, Hindi Stories, Sindbad, Hanuman

Output: CSV with category = "Entertainment", playlist_name = empty
"""

import sys
import logging
import csv
import requests
from datetime import datetime
from pathlib import Path
from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID,
    PROP_VIDEO_NAME, PROP_AGE_GROUP, PROP_CATEGORY, PROP_LANGUAGE,
    ADMIN_CSV_HEADER, ADMIN_CHANNEL_NAME, ADMIN_CONTENT_TYPE,
    BATCHES_DIR,
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
        items = prop.get("multi_select", [])
        return ", ".join(o["name"] for o in items)
    if t == "checkbox":
        return "Yes" if prop.get("checkbox", False) else "No"
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
    """
    Query Notion for all videos from story categories.
    Returns list of dicts with video metadata.
    """
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        raise ValueError("NOTION_TOKEN or NOTION_DATABASE_ID not set")

    url = _query_url()
    results = []
    seen_pages = set()

    # Build filter: Category contains any of the story categories
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
                log.error(f"Query failed: {resp.status_code} {resp.text[:200]}")
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
                log.warning(f"Skip page {page_id}: no video name")
                continue

            # Check if this video has any of the story categories
            video_cats = [c.strip() for c in category.split(",")]
            is_story = any(cat in STORY_CATEGORIES for cat in video_cats)
            if not is_story:
                continue

            log.info(f"Found: [{video_name}] | Category={category} | Language={language}")
            results.append({
                "page_id": page_id,
                "video_name": video_name,
                "age_group": age_group,
                "category": category,
                "language": language,
            })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    log.info(f"\nQuery complete: {len(results)} unique videos from story categories")
    return results


def export_to_csv(videos: list[dict], output_file: str) -> bool:
    """
    Export videos to CSV with:
      - categories_name = "Entertainment"
      - playlist_name = empty
      - Other columns preserved
    """
    Path(BATCHES_DIR).mkdir(exist_ok=True)

    try:
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=ADMIN_CSV_HEADER)
            writer.writeheader()

            for video in videos:
                row = {
                    'video_name': video['video_name'],
                    'categories_name': 'Entertainment',  # Override with Entertainment
                    'age_groups': video['age_group'],
                    'channel_name': ADMIN_CHANNEL_NAME,
                    'tags': '',
                    'playlist_name': '',  # Empty playlist
                    'content_formats': '',
                    'content_types': ADMIN_CONTENT_TYPE,
                    'language': video['language'],
                }
                writer.writerow(row)

        log.info(f"✓ Exported {len(videos)} videos to {output_file}")
        return True
    except Exception as e:
        log.error(f"Export failed: {e}")
        return False


def main():
    """Main entry point."""
    log.info("=" * 70)
    log.info("Batch: Story Categories → Entertainment (CSV Export)")
    log.info("=" * 70)
    log.info(f"\nStory categories to batch:")
    for cat in STORY_CATEGORIES:
        log.info(f"  - {cat}")

    # Query
    log.info(f"\n[1/2] Querying Notion...")
    try:
        videos = query_story_videos()
    except Exception as e:
        log.error(f"Query failed: {e}")
        sys.exit(1)

    if not videos:
        log.warning("No videos found in story categories")
        sys.exit(0)

    # Export
    log.info(f"\n[2/2] Exporting to CSV...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path(BATCHES_DIR) / f"Stories_Entertainment_{timestamp}.csv"

    if not export_to_csv(videos, str(output_file)):
        sys.exit(1)

    # Summary
    log.info("\n" + "=" * 70)
    log.info("SUMMARY:")
    log.info(f"  Total videos: {len(videos)}")
    log.info(f"  Output file: {output_file}")
    log.info(f"  Category: Entertainment")
    log.info(f"  Playlist: (empty)")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
