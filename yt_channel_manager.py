"""
yt_channel_manager.py — Backend for the YouTube Channel Download Manager.

Manages multiple YouTube channels: checking for new videos, downloading them,
and creating upload-ready batches with CSV + ZIP files.
"""

import os
import sys
import re
import csv
import json
import shutil
import zipfile
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
CHANNELS_FILE = BASE_DIR / "yt_channels.json"
MAX_BATCH_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

# ── Shared state for background tasks ────────────────────────────────────────
_running_tasks = {}  # channel_id -> {"thread", "status", "log", "progress"}


def _yt_dlp_cmd():
    return [sys.executable, "-m", "yt_dlp", "--no-update"]


def sanitize_filename(title: str) -> str:
    """Convert YouTube title to a file-safe name with underscores."""
    title = title.encode('ascii', 'ignore').decode('ascii')
    title = re.sub(r'[^\w\s-]', '', title)
    title = re.sub(r'[\s-]+', '_', title.strip())
    title = re.sub(r'_+', '_', title).strip('_')
    return title


# ═══════════════════════════════════════════════════════════════════════════════
#  Channel Config CRUD
# ═══════════════════════════════════════════════════════════════════════════════

def load_channels() -> list[dict]:
    if CHANNELS_FILE.exists():
        with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("channels", [])
    return []


def save_channels(channels: list[dict]):
    with open(CHANNELS_FILE, 'w', encoding='utf-8') as f:
        json.dump({"channels": channels}, f, indent=2, ensure_ascii=False)


def get_channel(channel_id: str) -> dict | None:
    for ch in load_channels():
        if ch["id"] == channel_id:
            return ch
    return None


def add_channel(channel_data: dict) -> dict:
    channels = load_channels()
    # Ensure unique ID
    if any(c["id"] == channel_data["id"] for c in channels):
        raise ValueError(f"Channel '{channel_data['id']}' already exists")
    channels.append(channel_data)
    save_channels(channels)
    return channel_data


def remove_channel(channel_id: str) -> bool:
    channels = load_channels()
    new_channels = [c for c in channels if c["id"] != channel_id]
    if len(new_channels) == len(channels):
        return False
    save_channels(new_channels)
    return True


# ═══════════════════════════════════════════════════════════════════════════════
#  Registry (per-channel tracking)
# ═══════════════════════════════════════════════════════════════════════════════

def _registry_path(ch: dict) -> Path:
    return BASE_DIR / ch["registry_file"]


def load_registry(ch: dict) -> dict:
    """Load registry CSV into dict keyed by video_id."""
    path = _registry_path(ch)
    registry = {}
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                registry[row['video_id']] = row
    return registry


def save_registry(ch: dict, registry: dict):
    path = _registry_path(ch)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['video_id', 'youtube_title', 'safe_name', 'status', 'batch', 'file_size_mb'])
        for vid_id, row in registry.items():
            writer.writerow([
                vid_id,
                row.get('youtube_title', ''),
                row.get('safe_name', ''),
                row.get('status', 'pending'),
                row.get('batch', ''),
                row.get('file_size_mb', ''),
            ])


# ═══════════════════════════════════════════════════════════════════════════════
#  YouTube API
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_channel_videos(channel_url: str) -> list[dict]:
    """Fetch all video IDs and titles from a YouTube channel."""
    cmd = _yt_dlp_cmd() + [
        "--flat-playlist",
        "--print", "%(id)s|||%(title)s",
        channel_url
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=180)
    stdout = result.stdout.decode('utf-8', errors='replace')

    videos = []
    for line in stdout.strip().split('\n'):
        line = line.strip()
        if '|||' in line:
            vid_id, title = line.split('|||', 1)
            title = title.strip()
            safe_name = sanitize_filename(title)
            videos.append({
                "id": vid_id.strip(),
                "title": title,
                "safe_name": safe_name,
            })

    # Deduplicate safe_names
    seen = {}
    for v in videos:
        name = v['safe_name']
        if name in seen:
            seen[name] += 1
            v['safe_name'] = f"{name}_{seen[name]}"
        else:
            seen[name] = 1

    return videos


# ═══════════════════════════════════════════════════════════════════════════════
#  Check for new videos (non-blocking)
# ═══════════════════════════════════════════════════════════════════════════════

def check_new_videos(ch: dict) -> dict:
    """Check how many new videos a channel has. Returns summary."""
    registry = load_registry(ch)
    all_videos = fetch_channel_videos(ch["url"])

    new_videos = [v for v in all_videos if v["id"] not in registry]
    batched = sum(1 for r in registry.values() if r.get("status") == "batched")
    failed = sum(1 for r in registry.values() if r.get("status") == "failed")

    return {
        "total_on_youtube": len(all_videos),
        "tracked": len(registry),
        "batched": batched,
        "failed": failed,
        "new_count": len(new_videos),
        "new_videos": [{"id": v["id"], "title": v["title"]} for v in new_videos],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Channel stats (from registry only, no YouTube call)
# ═══════════════════════════════════════════════════════════════════════════════

def get_channel_stats(ch: dict) -> dict:
    """Get stats from registry without hitting YouTube."""
    registry = load_registry(ch)
    batched = sum(1 for r in registry.values() if r.get("status") == "batched")
    downloaded = sum(1 for r in registry.values() if r.get("status") == "downloaded")
    failed = sum(1 for r in registry.values() if r.get("status") == "failed")
    pending = sum(1 for r in registry.values() if r.get("status") == "pending")

    # Count existing batches
    batch_dir = BASE_DIR / ch["batch_dir"]
    batch_count = 0
    if batch_dir.exists():
        batch_count = len(list(batch_dir.glob(f"{ch['batch_prefix']}_*.csv")))

    return {
        "total_tracked": len(registry),
        "batched": batched,
        "downloaded": downloaded,
        "failed": failed,
        "pending": pending,
        "batch_count": batch_count,
    }


def get_pipeline_summary(ch: dict) -> dict:
    """
    Get comprehensive pipeline summary: video counts at each stage,
    cross-referencing registry statuses with batch upload statuses.

    Stages:
      pending_dl   - In registry, status='pending' (discovered but not downloaded)
      downloaded   - In registry, status='downloaded' (downloaded but not in any batch)
      dl_failed    - In registry, status='failed' (download failed)
      batched      - In a batch, but batch NOT registered in main dashboard
      registered   - Batch registered in main dashboard, pending upload
      uploaded     - Batch uploaded to CMS (pending finalization)
      upload_failed - Batch upload failed
      finalized    - Batch finalized

    Returns dict with counts + batch-level breakdowns.
    """
    registry = load_registry(ch)
    batch_dir = BASE_DIR / ch["batch_dir"]

    # Video-level counts from registry
    pending_dl = 0
    downloaded = 0
    dl_failed = 0
    batched_videos = 0

    for vid_id, row in registry.items():
        st = row.get("status", "pending")
        if st in ("pending", "discovered", ""):
            pending_dl += 1
        elif st == "downloaded":
            downloaded += 1
        elif st == "failed":
            dl_failed += 1
        elif st == "batched":
            batched_videos += 1

    # Batch-level counts (cross-reference with batches.json)
    batches_json = _load_batches_json()
    batch_counts = {
        "not_registered": 0,
        "registered": 0,
        "uploaded": 0,
        "upload_failed": 0,
        "finalized": 0,
    }
    batch_video_counts = {
        "not_registered": 0,
        "registered": 0,
        "uploaded": 0,
        "upload_failed": 0,
        "finalized": 0,
    }

    if batch_dir.exists():
        all_csvs = sorted(batch_dir.glob(f"{ch['batch_prefix']}_*.csv"))
        for csv_path in all_csvs:
            bn = csv_path.stem
            # Count videos in this batch
            vc = 0
            try:
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader, None)  # skip header
                    vc = sum(1 for _ in reader)
            except Exception:
                pass

            main_record = batches_json.get(bn, {})
            if bn not in batches_json:
                batch_counts["not_registered"] += 1
                batch_video_counts["not_registered"] += vc
            elif main_record.get("upload_failed"):
                batch_counts["upload_failed"] += 1
                batch_video_counts["upload_failed"] += vc
            elif main_record.get("status") == "pending_first_review":
                batch_counts["registered"] += 1
                batch_video_counts["registered"] += vc
            elif main_record.get("status") == "pending_second_review":
                batch_counts["uploaded"] += 1
                batch_video_counts["uploaded"] += vc
            elif main_record.get("status") == "finalized":
                batch_counts["finalized"] += 1
                batch_video_counts["finalized"] += vc

    return {
        "total_tracked": len(registry),
        # Video-level stages
        "pending_dl": pending_dl,
        "downloaded": downloaded,
        "dl_failed": dl_failed,
        # Batch-level stages (both batch count and video count)
        "batched_videos": batched_videos,
        "batch_counts": batch_counts,
        "batch_video_counts": batch_video_counts,
    }


def get_videos_by_status(ch: dict, status: str) -> list[dict]:
    """
    Get list of videos filtered by registry status.
    status: 'pending' | 'downloaded' | 'failed' | 'batched'
    """
    registry = load_registry(ch)
    results = []

    for vid_id, row in registry.items():
        row_status = row.get("status", "pending")
        # Normalize
        if row_status in ("discovered", ""):
            row_status = "pending"

        if row_status == status:
            results.append({
                "video_id": vid_id,
                "title": row.get("youtube_title", row.get("safe_name", "")),
                "safe_name": row.get("safe_name", ""),
                "status": row_status,
                "batch": row.get("batch", ""),
                "file_size_mb": row.get("file_size_mb", ""),
            })

    results.sort(key=lambda x: x.get("title", ""))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  Download + Batch (background task)
# ═══════════════════════════════════════════════════════════════════════════════

def _download_single(video: dict, download_dir: Path) -> bool:
    """Download a single video in 1080p MP4."""
    output_path = download_dir / f"{video['safe_name']}.mp4"

    if output_path.exists() and output_path.stat().st_size > 0:
        return True

    url = f"https://www.youtube.com/watch?v={video['id']}"
    cmd = _yt_dlp_cmd() + [
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "--output", str(output_path),
        "--no-playlist",
        "--retries", "3",
        "--fragment-retries", "3",
        "--socket-timeout", "30",
        url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=600)
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception:
        return False


def _get_next_batch_num(batch_dir: Path, prefix: str) -> int:
    existing = list(batch_dir.glob(f"{prefix}_*.csv"))
    if not existing:
        return 1
    nums = []
    for p in existing:
        try:
            num = int(p.stem.split('_')[-1])
            nums.append(num)
        except ValueError:
            pass
    return max(nums) + 1 if nums else 1


def download_and_batch(channel_id: str):
    """Run the full download + batch pipeline for a channel in a background thread."""
    ch = get_channel(channel_id)
    if not ch:
        return

    task = _running_tasks.get(channel_id)
    if task and task.get("status") == "running":
        return  # Already running

    download_dir = BASE_DIR / ch["download_dir"]
    batch_dir = BASE_DIR / ch["batch_dir"]
    download_dir.mkdir(parents=True, exist_ok=True)
    batch_dir.mkdir(parents=True, exist_ok=True)

    defaults = ch.get("csv_defaults", {})
    log_lines = []

    def log(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        log_lines.append(line)

    def _worker():
        task_state = _running_tasks[channel_id]
        task_state["status"] = "running"
        task_state["started_at"] = datetime.now().isoformat()

        try:
            # 1. Fetch video list
            log(f"Fetching video list from {ch['url']}...")
            registry = load_registry(ch)
            all_videos = fetch_channel_videos(ch["url"])
            new_videos = [v for v in all_videos if v["id"] not in registry]

            log(f"Found {len(all_videos)} total, {len(new_videos)} new videos.")
            task_state["total"] = len(new_videos)

            if not new_videos:
                log("✅ No new videos. Everything is up to date!")
                task_state["status"] = "done"
                return

            # 2. Download
            downloaded = []
            failed = []
            for i, video in enumerate(new_videos, 1):
                task_state["progress"] = i
                safe = video['safe_name']
                log(f"[{i}/{len(new_videos)}] Downloading: {safe}")

                success = _download_single(video, download_dir)
                fpath = download_dir / f"{safe}.mp4"
                file_size_mb = ""
                if fpath.exists():
                    file_size_mb = f"{fpath.stat().st_size / (1024*1024):.2f}"

                if success:
                    downloaded.append(video)
                    registry[video['id']] = {
                        'youtube_title': video['title'],
                        'safe_name': safe,
                        'status': 'downloaded',
                        'batch': '',
                        'file_size_mb': file_size_mb,
                    }
                    log(f"  ✓ Downloaded ({file_size_mb} MB)")
                else:
                    failed.append(video)
                    registry[video['id']] = {
                        'youtube_title': video['title'],
                        'safe_name': safe,
                        'status': 'failed',
                        'batch': '',
                        'file_size_mb': '',
                    }
                    log(f"  ✗ Failed")

                # Save registry periodically
                if i % 5 == 0:
                    save_registry(ch, registry)

            save_registry(ch, registry)
            log(f"\nDownloads done: {len(downloaded)} ok, {len(failed)} failed.")

            if not downloaded:
                task_state["status"] = "done"
                return

            # 3. Create batches
            log("Creating batches...")
            available = []
            for v in downloaded:
                fpath = download_dir / f"{v['safe_name']}.mp4"
                if fpath.exists() and fpath.stat().st_size > 0:
                    v['file_path'] = fpath
                    v['file_size'] = fpath.stat().st_size
                    available.append(v)

            available.sort(key=lambda x: x['safe_name'])
            batches = []
            current_batch = []
            current_size = 0

            for v in available:
                if current_batch and (current_size + v['file_size']) > MAX_BATCH_SIZE_BYTES:
                    batches.append(current_batch)
                    current_batch = []
                    current_size = 0
                current_batch.append(v)
                current_size += v['file_size']
            if current_batch:
                batches.append(current_batch)

            start_num = _get_next_batch_num(batch_dir, ch["batch_prefix"])

            for idx, batch_videos in enumerate(batches):
                batch_num = start_num + idx
                batch_name = f"{ch['batch_prefix']}_{batch_num:03d}"
                batch_folder = batch_dir / batch_name
                batch_folder.mkdir(parents=True, exist_ok=True)

                # Write CSV
                csv_path = batch_dir / f"{batch_name}.csv"
                with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "video_name", "categories_name", "age_groups", "channel_name",
                        "tags", "playlist_name", "content_formats", "content_types", "language"
                    ])
                    for v in batch_videos:
                        writer.writerow([
                            v['safe_name'],
                            defaults.get("categories_name", ""),
                            defaults.get("age_groups", ""),
                            defaults.get("channel_name", ""),
                            defaults.get("tags", ""),
                            defaults.get("playlist_name", ""),
                            defaults.get("content_formats", ""),
                            defaults.get("content_types", ""),
                            defaults.get("language", ""),
                        ])

                # Create ZIP
                zip_path = batch_dir / f"{batch_name}.zip"
                total_size = 0
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
                    for v in batch_videos:
                        src = v['file_path']
                        dest = batch_folder / f"{v['safe_name']}.mp4"
                        total_size += v['file_size']
                        if not dest.exists():
                            shutil.copy2(src, dest)
                        zf.write(src, f"{v['safe_name']}.mp4")

                size_mb = total_size / (1024 * 1024)
                log(f"  {batch_name}: {len(batch_videos)} videos, {size_mb:.1f} MB")

                # Update registry
                for v in batch_videos:
                    if v['id'] in registry:
                        registry[v['id']]['status'] = 'batched'
                        registry[v['id']]['batch'] = batch_name

            save_registry(ch, registry)
            log(f"\n✅ Done! Created {len(batches)} batch(es).")
            task_state["batches_created"] = len(batches)

        except Exception as e:
            log(f"❌ Error: {e}")
            task_state["error"] = str(e)
        finally:
            task_state["status"] = "done"
            task_state["finished_at"] = datetime.now().isoformat()

    _running_tasks[channel_id] = {
        "status": "starting",
        "log": log_lines,
        "progress": 0,
        "total": 0,
        "batches_created": 0,
        "error": None,
    }

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    _running_tasks[channel_id]["thread"] = t


def get_task_status(channel_id: str) -> dict | None:
    task = _running_tasks.get(channel_id)
    if not task:
        return None
    return {
        "status": task["status"],
        "progress": task["progress"],
        "total": task["total"],
        "log": task["log"][-50:],  # Last 50 lines
        "full_log": task["log"],
        "batches_created": task.get("batches_created", 0),
        "error": task.get("error"),
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Register batches into the main dashboard for Selenium upload
# ═══════════════════════════════════════════════════════════════════════════════

MAIN_BATCHES_DIR = BASE_DIR / "batches"
BATCHES_JSON = BASE_DIR / "batches.json"


def _load_batches_json() -> dict:
    if BATCHES_JSON.exists():
        try:
            with open(BATCHES_JSON, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_batches_json(data: dict):
    tmp = str(BATCHES_JSON) + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, str(BATCHES_JSON))


def register_batches_for_upload(ch: dict, batch_names: list[str] | None = None) -> dict:
    """
    Register channel batches into main batches.json + copy CSV/ZIP to batches/ dir.
    This enables the existing Selenium uploader to handle them.

    Args:
        ch: Channel config dict
        batch_names: Specific batch names to register (None = all unregistered)

    Returns: {registered: int, skipped: int, errors: [str]}
    """
    batch_dir = BASE_DIR / ch["batch_dir"]
    MAIN_BATCHES_DIR.mkdir(parents=True, exist_ok=True)

    batches_json = _load_batches_json()
    defaults = ch.get("csv_defaults", {})

    # Discover batches to register
    if batch_names is None:
        # Find all batch CSVs in the channel batch dir
        all_csvs = sorted(batch_dir.glob(f"{ch['batch_prefix']}_*.csv"))
        batch_names = [p.stem for p in all_csvs]

    registered = 0
    skipped = 0
    errors = []

    for bn in batch_names:
        # Skip if already registered
        if bn in batches_json:
            skipped += 1
            continue

        src_csv = batch_dir / f"{bn}.csv"
        src_zip = batch_dir / f"{bn}.zip"

        if not src_csv.exists():
            errors.append(f"{bn}: CSV not found")
            continue
        if not src_zip.exists():
            errors.append(f"{bn}: ZIP not found")
            continue

        # Copy CSV + ZIP to main batches dir
        dst_csv = MAIN_BATCHES_DIR / f"{bn}.csv"
        dst_zip = MAIN_BATCHES_DIR / f"{bn}.zip"

        try:
            shutil.copy2(str(src_csv), str(dst_csv))
            shutil.copy2(str(src_zip), str(dst_zip))
        except Exception as e:
            errors.append(f"{bn}: copy failed - {e}")
            continue

        # Also copy the batch folder (MP4s) if it exists
        src_folder = batch_dir / bn
        dst_folder = MAIN_BATCHES_DIR / bn
        if src_folder.is_dir() and not dst_folder.exists():
            try:
                shutil.copytree(str(src_folder), str(dst_folder))
            except Exception as e:
                # Non-fatal — ZIP is enough for upload
                pass

        # Read CSV to build video list
        videos = []
        with open(src_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                videos.append({
                    "page_id": f"yt_{ch['id']}_{bn}_{i}",
                    "video_name": row.get("video_name", ""),
                    "age_group": row.get("age_groups", ""),
                    "category": row.get("categories_name", ""),
                    "playlist": row.get("playlist_name", ""),
                    "channel": row.get("channel_name", ""),
                    "local_file": "",
                    "drive_link": "",
                    "pipeline_status": "batched",
                    "language": row.get("language", ""),
                })

        # Register in batches.json
        batches_json[bn] = {
            "batch_name": bn,
            "status": "pending_first_review",
            "created_at": datetime.now().isoformat(),
            "source": f"yt_channel_{ch['id']}",
            "videos": videos,
            "upload_job_id": None,
            "upload_date": None,
            "upload_completed": False,
            "upload_failed": False,
            "fail_reason": None,
            "finalized_date": None,
        }
        registered += 1

    _save_batches_json(batches_json)
    return {"registered": registered, "skipped": skipped, "errors": errors}


def get_channel_batches(ch: dict) -> list[dict]:
    """Get batch status for a channel — merges channel batch info with main batches.json status."""
    batch_dir = BASE_DIR / ch["batch_dir"]
    if not batch_dir.exists():
        return []

    all_csvs = sorted(batch_dir.glob(f"{ch['batch_prefix']}_*.csv"))
    batches_json = _load_batches_json()

    result = []
    for csv_path in all_csvs:
        bn = csv_path.stem
        zip_path = batch_dir / f"{bn}.zip"

        # Count videos from CSV
        video_count = 0
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                video_count = sum(1 for _ in reader)
        except Exception:
            pass

        # Get size from ZIP
        zip_size_mb = 0
        if zip_path.exists():
            zip_size_mb = round(zip_path.stat().st_size / (1024 * 1024), 1)

        # Check if registered in main dashboard
        main_record = batches_json.get(bn, {})
        status = main_record.get("status", "not_registered")
        upload_failed = main_record.get("upload_failed", False)
        job_id = main_record.get("upload_job_id")
        fail_reason = main_record.get("fail_reason")

        if upload_failed:
            display_status = "failed"
        elif status == "pending_first_review":
            display_status = "pending"
        elif status == "pending_second_review":
            display_status = "uploaded"
        elif status == "finalized":
            display_status = "finalized"
        else:
            display_status = "not_registered"

        result.append({
            "batch_name": bn,
            "video_count": video_count,
            "zip_size_mb": zip_size_mb,
            "status": display_status,
            "job_id": job_id,
            "fail_reason": fail_reason,
            "registered": bn in batches_json,
        })

    return result
