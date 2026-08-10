"""
download_and_zip_stories.py -- Download videos from Stories batch CSV and create ZIP.

Process:
  1. Read the Stories_Entertainment CSV
  2. Query Notion to get download links for each video
  3. Download videos from Google Drive
  4. Create a ZIP file with all videos
"""

import sys
import os
import csv
import logging
import shutil
import requests
import gdown
from pathlib import Path
from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID,
    PROP_VIDEO_NAME, PROP_FINAL_VIDEO_HINDI_LINK, PROP_FINAL_VIDEO_ENGLISH_LINK,
    DOWNLOADS_DIR, BATCHES_DIR,
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
    """Extract property value."""
    prop = properties.get(name)
    if prop is None:
        return ""
    t = prop.get("type", "")
    if t == "title":
        parts = prop.get("title", [])
        return "".join(p.get("plain_text", "") for p in parts).strip()
    if t == "url":
        return prop.get("url") or ""
    if t == "rich_text":
        parts = prop.get("rich_text", [])
        return "".join(p.get("plain_text", "") for p in parts).strip()
    if t == "multi_select":
        return ", ".join(o["name"] for o in prop.get("multi_select", []))
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


def search_video_in_notion(video_name: str) -> dict | None:
    """Search Notion for a video by name and return download links."""
    url = _query_url()
    payload = {
        "filter": {
            "property": PROP_VIDEO_NAME,
            "title": {"contains": video_name},
        },
        "page_size": 10,
    }

    try:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
        if resp.status_code != 200:
            log.warning(f"Search failed for '{video_name}': {resp.status_code}")
            return None

        data = resp.json()
        for page in data.get("results", []):
            props = page["properties"]
            name = _prop_value(props, PROP_VIDEO_NAME).strip()
            if name == video_name:
                hindi_link = _prop_value(props, PROP_FINAL_VIDEO_HINDI_LINK).strip()
                english_link = _prop_value(props, PROP_FINAL_VIDEO_ENGLISH_LINK).strip()
                return {
                    "page_id": page["id"],
                    "hindi_link": hindi_link,
                    "english_link": english_link,
                }
    except Exception as e:
        log.warning(f"Error searching for '{video_name}': {e}")

    return None


def download_video(drive_link: str, output_path: str) -> bool:
    """Download a video from Google Drive using gdown."""
    if not drive_link or "drive.google.com" not in drive_link:
        return False

    try:
        log.info(f"  Downloading to: {Path(output_path).name}")
        gdown.download(drive_link, output_path, quiet=False)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            log.info(f"  ✓ Downloaded ({size_mb:.1f} MB)")
            return True
        else:
            log.warning(f"  ✗ Download failed or empty file")
            return False
    except Exception as e:
        log.error(f"  ✗ Error: {e}")
        return False


def main():
    """Main entry point."""
    log.info("=" * 70)
    log.info("Download & ZIP: Stories Batch Videos")
    log.info("=" * 70)

    # Find the latest CSV
    batches_path = Path(BATCHES_DIR)
    csv_files = sorted(batches_path.glob("Stories_Entertainment_*.csv"), reverse=True)
    if not csv_files:
        log.error("No Stories_Entertainment CSV found in batches/")
        sys.exit(1)

    csv_file = csv_files[0]
    log.info(f"\nUsing CSV: {csv_file.name}")

    # Create download directory
    download_dir = Path(DOWNLOADS_DIR) / "Stories_Entertainment"
    download_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Download dir: {download_dir}")

    # Read CSV and download videos
    log.info(f"\n[1/2] Downloading videos...")
    downloaded_count = 0
    failed_count = 0
    skipped_count = 0

    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        videos = list(reader)

    for i, row in enumerate(videos, 1):
        video_name = row.get("video_name", "").strip()
        language = row.get("language", "").strip()

        if not video_name:
            log.warning(f"[{i}/{len(videos)}] Skip: no video name")
            skipped_count += 1
            continue

        log.info(f"\n[{i}/{len(videos)}] {video_name} ({language})")

        # Search Notion for download links
        result = search_video_in_notion(video_name)
        if not result:
            log.warning(f"  Not found in Notion")
            skipped_count += 1
            continue

        links_to_try = []
        if language == "Hindi" and result["hindi_link"]:
            links_to_try.append(result["hindi_link"])
            if result["english_link"]:
                links_to_try.append(result["english_link"])
        elif language == "English" and result["english_link"]:
            links_to_try.append(result["english_link"])
            if result["hindi_link"]:
                links_to_try.append(result["hindi_link"])
        elif language and ", " in language:
            if result["hindi_link"]:
                links_to_try.append(result["hindi_link"])
            if result["english_link"]:
                links_to_try.append(result["english_link"])
        else:
            if result["hindi_link"]:
                links_to_try.append(result["hindi_link"])
            if result["english_link"]:
                links_to_try.append(result["english_link"])

        if not links_to_try:
            log.warning(f"  No download links found")
            skipped_count += 1
            continue

        # Try to download
        downloaded = False
        for link in links_to_try:
            output_file = download_dir / f"{video_name}.mp4"
            if download_video(link, str(output_file)):
                downloaded = True
                downloaded_count += 1
                break

        if not downloaded:
            log.warning(f"  Failed to download")
            failed_count += 1

    # Create ZIP
    log.info(f"\n[2/2] Creating ZIP file...")
    zip_path = Path(BATCHES_DIR) / f"Stories_Entertainment_Videos.zip"

    try:
        shutil.make_archive(
            str(zip_path.with_suffix("")),
            "zip",
            root_dir=str(download_dir.parent),
            base_dir=download_dir.name,
        )
        zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
        log.info(f"✓ Created ZIP: {zip_path.name} ({zip_size_mb:.1f} MB)")
    except Exception as e:
        log.error(f"ZIP creation failed: {e}")
        sys.exit(1)

    # Summary
    log.info("\n" + "=" * 70)
    log.info("SUMMARY:")
    log.info(f"  Total videos: {len(videos)}")
    log.info(f"  Downloaded: {downloaded_count}")
    log.info(f"  Failed: {failed_count}")
    log.info(f"  Skipped: {skipped_count}")
    log.info(f"  Output ZIP: {zip_path}")
    log.info("=" * 70)

    if failed_count > 0:
        log.warning(f"Some videos failed to download")


if __name__ == "__main__":
    main()
