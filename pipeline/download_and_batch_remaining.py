"""
download_and_batch_remaining.py -- Download remaining 37 videos (both Hindi+English),
compress, and batch them (≤100MB per batch).
"""

import sys
import os
import csv
import zipfile
import subprocess
import logging
import requests
import gdown
from pathlib import Path
from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID,
    PROP_VIDEO_NAME, PROP_FINAL_VIDEO_HINDI_LINK, PROP_FINAL_VIDEO_ENGLISH_LINK,
    DOWNLOADS_DIR, BATCHES_DIR, AGE_GROUP_MAP,
)

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)

NOTION_VERSION = "2025-09-03"
BASE = "https://api.notion.com/v1"
COMPRESSION_THRESHOLD_MB = 50
COMPRESSION_THRESHOLD_BYTES = COMPRESSION_THRESHOLD_MB * 1024 * 1024
MAX_BATCH_SIZE_MB = 100
MAX_BATCH_SIZE_BYTES = MAX_BATCH_SIZE_MB * 1024 * 1024


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
    if t == "multi_select":
        return ", ".join(o["name"] for o in prop.get("multi_select", []))
    return ""


def _normalize_age_group(age_group_str: str) -> str:
    """Normalize age group."""
    if not age_group_str:
        return ""
    age_groups = [ag.strip() for ag in age_group_str.split(",")]
    normalized = []
    for ag in age_groups:
        ag_lower = ag.lower()
        mapped = None
        for key, value in AGE_GROUP_MAP.items():
            if key in ag_lower:
                mapped = value
                break
        if mapped and mapped not in normalized:
            normalized.append(mapped)
    return ", ".join(normalized) if normalized else age_group_str


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
    """Search Notion for a video and return download links."""
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


def download_video(drive_link: str, output_path: str, lang: str) -> bool:
    """Download a video from Google Drive."""
    if not drive_link or "drive.google.com" not in drive_link:
        return False

    try:
        log.info(f"    Downloading {lang}: {Path(output_path).name}")
        gdown.download(drive_link, output_path, quiet=False)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            log.info(f"    ✓ Downloaded {lang} ({size_mb:.1f} MB)")
            return True
        return False
    except Exception as e:
        log.error(f"    ✗ Error: {e}")
        return False


def compress_video(video_path: Path) -> bool:
    """Compress video if > 50MB."""
    file_size_mb = video_path.stat().st_size / (1024 * 1024)

    if file_size_mb <= COMPRESSION_THRESHOLD_MB:
        return True

    log.info(f"    Compressing: {video_path.name} ({file_size_mb:.1f} MB)")

    temp_output = video_path.with_stem(video_path.stem + "_compressed")

    try:
        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-c:v", "libx264", "-preset", "medium", "-b:v", "1500k",
            "-c:a", "aac", "-b:a", "128k",
            "-y", str(temp_output),
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=600)

        if result.returncode != 0:
            if temp_output.exists():
                temp_output.unlink()
            return False

        new_size_mb = temp_output.stat().st_size / (1024 * 1024)
        video_path.unlink()
        temp_output.rename(video_path)
        log.info(f"    Compressed to: {new_size_mb:.1f} MB")
        return True

    except Exception as e:
        log.error(f"    Compression error: {e}")
        if temp_output.exists():
            temp_output.unlink()
        return False


def download_remaining_videos(batch_12_csv: Path, videos_dir: Path) -> list[dict]:
    """Download remaining 37 videos (both Hindi+English when available)."""
    log.info(f"\n[1/3] Downloading remaining videos...")

    videos_dir.mkdir(parents=True, exist_ok=True)
    downloaded_videos = []

    with open(batch_12_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            video_name = row.get("video_name", "").strip()
            age_group = _normalize_age_group(row.get("age_groups", "").strip())
            language = row.get("language", "").strip()

            if not video_name:
                continue

            log.info(f"\n  [{i}/37] {video_name}")

            # Search Notion for download links
            result = search_video_in_notion(video_name)
            if not result:
                log.warning(f"    Not found in Notion")
                continue

            # Download Hindi if available
            if result["hindi_link"] and ("Hindi" in language or ", " in language):
                output_file = videos_dir / f"{video_name}___ln_Hi.mp4"
                if download_video(result["hindi_link"], str(output_file), "Hindi"):
                    compress_video(output_file)
                    downloaded_videos.append({
                        "row": row,
                        "video_name": video_name,
                        "video_path": output_file,
                        "video_size": output_file.stat().st_size,
                        "language": "Hindi",
                    })

            # Download English if available
            if result["english_link"] and ("English" in language or ", " in language):
                output_file = videos_dir / f"{video_name}___ln_En.mp4"
                if download_video(result["english_link"], str(output_file), "English"):
                    compress_video(output_file)
                    downloaded_videos.append({
                        "row": row,
                        "video_name": video_name,
                        "video_path": output_file,
                        "video_size": output_file.stat().st_size,
                        "language": "English",
                    })

    log.info(f"\n  Downloaded {len(downloaded_videos)} video files")
    return downloaded_videos


def create_new_batches(downloaded_videos: list[dict], start_batch_num: int = 8) -> list[dict]:
    """Create batches from downloaded videos."""
    log.info(f"\n[2/3] Creating batches (starting from Batch_{start_batch_num:02d})...")

    # Sort by size (largest first)
    downloaded_videos.sort(key=lambda x: x["video_size"], reverse=True)

    # Create batches
    batches = []
    current_batch = {"videos": [], "total_size": 0}

    for video in downloaded_videos:
        video_size = video["video_size"]

        if current_batch["total_size"] + video_size > MAX_BATCH_SIZE_BYTES and current_batch["videos"]:
            batches.append(current_batch)
            current_batch = {"videos": [], "total_size": 0}

        current_batch["videos"].append(video)
        current_batch["total_size"] += video_size

    if current_batch["videos"]:
        batches.append(current_batch)

    log.info(f"\n  Created {len(batches)} new batches:")
    for i, batch in enumerate(batches, 1):
        batch_num = start_batch_num + i - 1
        size_mb = batch["total_size"] / (1024 * 1024)
        log.info(f"    Batch_{batch_num:02d}: {len(batch['videos'])} videos, {size_mb:.1f} MB")

    return batches


def create_batch_files(batches: list[dict], output_dir: Path, start_batch_num: int = 8):
    """Create CSV and ZIP files for new batches."""
    log.info(f"\n[3/3] Creating CSV and ZIP files...")

    output_dir.mkdir(parents=True, exist_ok=True)

    for i, batch in enumerate(batches, 1):
        batch_num = start_batch_num + i - 1
        size_mb = batch["total_size"] / (1024 * 1024)
        log.info(f"\n  Batch_{batch_num:02d} ({len(batch['videos'])} videos, {size_mb:.1f} MB):")

        # Create CSV
        csv_file = output_dir / f"Batch_{batch_num:02d}.csv"
        header = list(batch["videos"][0]["row"].keys())

        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            for video in batch["videos"]:
                writer.writerow(video["row"])

        log.info(f"    Created: {csv_file.name}")

        # Create ZIP
        zip_file = output_dir / f"Batch_{batch_num:02d}.zip"
        with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for j, video in enumerate(batch["videos"], 1):
                video_path = video["video_path"]
                zf.write(video_path, arcname=video_path.name)
                if j % 3 == 0 or j == len(batch["videos"]):
                    log.info(f"      [{j}/{len(batch['videos'])}] {video_path.name}")

        zip_size_mb = zip_file.stat().st_size / (1024 * 1024)
        log.info(f"    Created: {zip_file.name} ({zip_size_mb:.1f} MB)")


def main():
    """Main entry point."""
    log.info("=" * 70)
    log.info("Download & Batch Remaining 37 Videos (Both Languages)")
    log.info("=" * 70)

    # Find Batch_12.csv
    batches_dir = Path(BATCHES_DIR) / "Stories_Batches"
    batch_12_csv = batches_dir / "Batch_12.csv"

    if not batch_12_csv.exists():
        log.error(f"Batch_12.csv not found: {batch_12_csv}")
        sys.exit(1)

    log.info(f"\nUsing CSV: {batch_12_csv.name}")

    # Videos directory
    videos_dir = Path(DOWNLOADS_DIR) / "Stories_Entertainment"

    # Download remaining videos
    downloaded_videos = download_remaining_videos(batch_12_csv, videos_dir)

    if not downloaded_videos:
        log.error("No videos downloaded")
        sys.exit(1)

    # Create batches (starting from Batch_08)
    batches = create_new_batches(downloaded_videos, start_batch_num=8)

    # Create batch files
    create_batch_files(batches, batches_dir, start_batch_num=8)

    # Summary
    log.info("\n" + "=" * 70)
    log.info("SUMMARY:")
    log.info(f"  Downloaded video files: {len(downloaded_videos)}")
    log.info(f"  New batches created: {len(batches)} (Batch_08+)")
    log.info(f"  Output directory: {batches_dir}")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
