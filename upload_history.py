"""
upload_history.py — Persistent, append-only upload history.

Every video that gets uploaded is logged here with full metadata.
This file is NEVER cleared — it's the permanent source of truth for
"what was uploaded, when, and where."

Storage: upload_history.jsonl (one JSON object per line, append-only)
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upload_history.jsonl")
_lock = threading.Lock()


def log_upload(
    video_name: str,
    batch_name: str,
    job_id: str = "",
    status: str = "uploaded",
    category: str = "",
    playlist: str = "",
    channel: str = "",
    age_group: str = "",
    language: str = "",
    source: str = "dashboard",
    fail_reason: str = "",
    **extra,
):
    """Append a single upload record to the history file.

    Args:
        video_name: The video filename (without extension)
        batch_name: Which batch it was part of (e.g. Batch_42)
        job_id:     CMS job ID from the admin site
        status:     'uploaded', 'submitted', 'upload_failed', 'approval_failed'
        category:   Category name
        playlist:   Playlist name
        channel:    Channel name
        age_group:  Age group (0-3, 3-6, 6+)
        language:   Hindi / English
        source:     'auto_upload', 'dashboard', 'pipeline'
        fail_reason: If failed, why
        **extra:    Any additional fields to store
    """
    record = {
        "timestamp": datetime.now().isoformat(),
        "video_name": video_name,
        "batch_name": batch_name,
        "job_id": job_id,
        "status": status,
        "category": category,
        "playlist": playlist,
        "channel": channel,
        "age_group": age_group,
        "language": language,
        "source": source,
        "fail_reason": fail_reason,
    }
    if extra:
        record.update(extra)

    with _lock:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_batch(
    batch_name: str,
    videos: list[dict],
    job_id: str = "",
    status: str = "uploaded",
    source: str = "dashboard",
    fail_reason: str = "",
):
    """Log all videos in a batch at once."""
    for v in videos:
        log_upload(
            video_name=v.get("video_name", ""),
            batch_name=batch_name,
            job_id=job_id,
            status=status,
            category=v.get("categories_name", v.get("category", "")),
            playlist=v.get("playlist_name", v.get("playlist", "")),
            channel=v.get("channel_name", v.get("channel", "")),
            age_group=v.get("age_group", ""),
            language=v.get("language", ""),
            source=source,
            fail_reason=fail_reason,
            page_id=v.get("page_id", ""),
        )


def get_history(limit: int = 500) -> list[dict]:
    """Read the most recent N records from the history file."""
    if not os.path.isfile(HISTORY_FILE):
        return []
    records = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception:
        return []
    # Return most recent first, capped at limit
    return list(reversed(records[-limit:]))


def get_stats() -> dict:
    """Get aggregate stats from upload history."""
    if not os.path.isfile(HISTORY_FILE):
        return {"total": 0, "uploaded": 0, "failed": 0, "by_source": {}, "by_date": {}}

    total = 0
    uploaded = 0
    failed = 0
    by_source = {}
    by_date = {}

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                total += 1
                s = rec.get("status", "")
                if s in ("uploaded", "submitted"):
                    uploaded += 1
                elif "failed" in s:
                    failed += 1

                src = rec.get("source", "unknown")
                by_source[src] = by_source.get(src, 0) + 1

                ts = rec.get("timestamp", "")
                if ts:
                    day = ts[:10]
                    by_date[day] = by_date.get(day, 0) + 1
    except Exception:
        pass

    return {
        "total": total,
        "uploaded": uploaded,
        "failed": failed,
        "by_source": by_source,
        "by_date": by_date,
    }


def get_submission_tracker() -> list[dict]:
    """Group upload records by CMS job_id to track batch submissions.

    Returns a list of job entries sorted newest-first:
    [
        {
            "job_id": "abc-123...",
            "batch_name": "Batch_42",
            "status": "submitted" | "approval_failed" | "upload_failed",
            "timestamp": "2026-07-09T15:30:00",
            "source": "auto_upload" | "dashboard",
            "video_count": 5,
            "videos": ["Video_A", "Video_B", ...],
            "fail_reason": "",
        },
        ...
    ]
    """
    if not os.path.isfile(HISTORY_FILE):
        return []

    # Group by (batch_name, job_id) — each is one submission attempt
    jobs = {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                batch = rec.get("batch_name", "")
                job_id = rec.get("job_id", "")
                key = f"{batch}|{job_id}"

                if key not in jobs:
                    jobs[key] = {
                        "job_id": job_id,
                        "batch_name": batch,
                        "status": rec.get("status", "unknown"),
                        "timestamp": rec.get("timestamp", ""),
                        "source": rec.get("source", "unknown"),
                        "video_count": 0,
                        "videos": [],
                        "fail_reason": rec.get("fail_reason", ""),
                    }

                jobs[key]["video_count"] += 1
                vname = rec.get("video_name", "")
                if vname and vname not in jobs[key]["videos"]:
                    jobs[key]["videos"].append(vname)

    except Exception:
        return []

    # Sort newest first
    result = sorted(jobs.values(), key=lambda j: j["timestamp"], reverse=True)
    return result
