"""
batch_stories_playlist.py -- Batch update all videos from "Stories" playlist.

Does the following:
  1. Queries the Notion database for all videos where Playlist = "Stories"
  2. Deduplicates by page ID
  3. Updates each video:
     - Category = "Entertainment"
     - Playlist = empty (cleared)
  4. Preserves other columns (language, age group, etc.)

Usage:
    python batch_stories_playlist.py
"""

import sys
import logging
import requests
from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID,
    PROP_VIDEO_NAME, PROP_CATEGORY, PROP_PLAYLIST,
    NOTION_READ_ONLY,
)

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)

NOTION_VERSION = "2025-09-03"
BASE = "https://api.notion.com/v1"


def _headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _prop_value(properties: dict, name: str) -> str:
    """Extract property value (handles title, rich_text, select)."""
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
    return ""


def _resolve_data_source_id() -> str:
    """Resolve the data source ID from the database."""
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
    """Return the correct query URL for Notion API."""
    ds_id = _resolve_data_source_id()
    return f"{BASE}/data_sources/{ds_id}/query"


def query_stories_playlist_videos() -> list[dict]:
    """
    Query Notion for all videos where Playlist = "Stories".
    Returns a list of dicts with: page_id, video_name, category
    """
    if not NOTION_TOKEN:
        raise ValueError("NOTION_TOKEN is not set")
    if not NOTION_DATABASE_ID:
        raise ValueError("NOTION_DATABASE_ID is not set")

    url = _query_url()
    results = []
    cursor = None
    seen_pages = set()

    while True:
        payload = {
            "filter": {
                "property": PROP_PLAYLIST,
                "select": {"equals": "Stories"},
            },
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
            # Skip duplicates (by page ID)
            if page_id in seen_pages:
                continue
            seen_pages.add(page_id)

            props = page["properties"]
            video_name = _prop_value(props, PROP_VIDEO_NAME).strip()
            category = _prop_value(props, PROP_CATEGORY).strip()

            if not video_name:
                log.warning(f"Skip page {page_id}: no video name")
                continue

            log.info(f"Found: [{video_name}] | Category={category} | page_id={page_id}")
            results.append({
                "page_id": page_id,
                "video_name": video_name,
                "category": category,
            })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    log.info(f"\nQuery complete: {len(results)} unique videos from 'Stories' playlist")
    return results


def batch_update_videos(videos: list[dict]) -> dict:
    """
    Update all videos:
      - Set Category to "Entertainment"
      - Clear Playlist field
    Returns: {"success": count, "failed": count, "failed_ids": [...]}
    """
    if NOTION_READ_ONLY:
        log.warning("[READ-ONLY] Notion writes are disabled. No updates will be made.")
        return {"success": 0, "failed": len(videos), "skipped": len(videos), "failed_ids": []}

    results = {"success": 0, "failed": 0, "failed_ids": []}

    for i, video in enumerate(videos, 1):
        page_id = video["page_id"]
        video_name = video["video_name"]

        log.info(f"\n[{i}/{len(videos)}] Updating: {video_name}...")

        url = f"{BASE}/pages/{page_id}"
        patch = {
            "properties": {
                PROP_CATEGORY: {
                    "select": {"name": "Entertainment"}
                },
                PROP_PLAYLIST: {
                    "select": None  # Clear the playlist
                },
            }
        }

        try:
            resp = requests.patch(url, headers=_headers(), json=patch, timeout=30)
            if resp.status_code == 200:
                log.info(f"  ✓ Updated: Category=Entertainment, Playlist=cleared")
                results["success"] += 1
            else:
                log.error(f"  ✗ Update failed: {resp.status_code} {resp.text[:200]}")
                results["failed"] += 1
                results["failed_ids"].append(page_id)
        except Exception as e:
            log.error(f"  ✗ Error: {e}")
            results["failed"] += 1
            results["failed_ids"].append(page_id)

    return results


def main():
    """Main entry point."""
    log.info("=" * 70)
    log.info("Batch Update: Stories Playlist → Entertainment Category")
    log.info("=" * 70)

    # Query
    log.info("\n[1/2] Querying Notion for 'Stories' playlist videos...")
    try:
        videos = query_stories_playlist_videos()
    except Exception as e:
        log.error(f"Query failed: {e}")
        sys.exit(1)

    if not videos:
        log.warning("No videos found in 'Stories' playlist")
        return

    # Confirm
    log.info(f"\nFound {len(videos)} video(s) to update:")
    for v in videos:
        log.info(f"  - {v['video_name']}")

    # Update
    log.info(f"\n[2/2] Batching updates...")
    results = batch_update_videos(videos)

    # Summary
    log.info("\n" + "=" * 70)
    log.info("SUMMARY:")
    log.info(f"  Success: {results['success']}")
    log.info(f"  Failed:  {results['failed']}")
    if results["failed_ids"]:
        log.warning(f"  Failed IDs: {results['failed_ids']}")
    log.info("=" * 70)

    if results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
