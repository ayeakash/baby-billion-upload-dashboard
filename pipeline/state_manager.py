"""
state_manager.py — Persistent JSON state tracking for the pipeline.

Tracks every video through the pipeline stages:
  pending → downloading → downloaded → batched → zipped → uploading → uploaded | failed
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from config import STATE_FILE

_lock = threading.Lock()   # serialise all reads + writes across threads


def _load_unlocked() -> dict:
    """Load state without acquiring lock (caller must hold _lock)."""
    if os.path.isfile(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _load() -> dict:
    with _lock:
        return _load_unlocked()


def _save(state: dict):
    """Write state. Protected by _lock (caller must hold it or call via upsert)."""
    import time
    if os.path.dirname(STATE_FILE):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp_file = STATE_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        # Retry os.replace — on Windows another process may hold a read handle
        for attempt in range(5):
            try:
                os.replace(tmp_file, STATE_FILE)
                return
            except PermissionError:
                if attempt < 4:
                    time.sleep(0.2)
                else:
                    raise
    except Exception as e:
        if os.path.isfile(tmp_file):
            try:
                os.remove(tmp_file)
            except:
                pass
        raise e


def _key(page_id: str) -> str:
    return page_id


# ── Public API ─────────────────────────────────────────────────────────────────

def get_all() -> dict:
    return _load()


def get(page_id: str) -> dict | None:
    return _load().get(_key(page_id))


def upsert(page_id: str, **fields):
    """Create or update a video's state record (thread-safe)."""
    with _lock:
        state = _load_unlocked()
        key = _key(page_id)
        if key not in state:
            state[key] = {"page_id": page_id, "updated_at": datetime.now().isoformat()}
        state[key].update(fields)
        state[key]["updated_at"] = datetime.now().isoformat()
        _save(state)


def set_status(page_id: str, status: str):
    upsert(page_id, pipeline_status=status)


def mark_downloaded(page_id: str, local_file: str):
    upsert(page_id, pipeline_status="downloaded", local_file=local_file)


def mark_batched(page_id: str, batch_name: str):
    upsert(page_id, pipeline_status="batched", batch=batch_name)


def mark_uploaded(page_id: str, job_id: str, upload_date: str):
    upsert(page_id, pipeline_status="uploaded", job_id=job_id, upload_date=upload_date)


def mark_failed(page_id: str, reason: str):
    upsert(page_id, pipeline_status="failed", failure_reason=reason)


def is_done(page_id: str) -> bool:
    """Returns True if this video has already been successfully uploaded."""
    rec = get(page_id)
    return rec is not None and rec.get("pipeline_status") == "uploaded"


def is_downloaded(page_id: str) -> bool:
    rec = get(page_id)
    if rec is None:
        return False
    return rec.get("pipeline_status") in ("downloaded", "batched", "zipped", "uploading", "uploaded")


def get_pending_upload(batch_name: str) -> list[dict]:
    """Return all records in state for the given batch, not yet uploaded."""
    state = _load()
    return [
        v for v in state.values()
        if v.get("batch") == batch_name
        and v.get("pipeline_status") not in ("uploaded",)
    ]


def next_batch_number(count: int = 1) -> int:
    """Atomically reserve `count` batch numbers and return the first one.
    The counter is stored in state.json under the key "_meta"."""
    with _lock:
        state = _load_unlocked()
        meta = state.setdefault("_meta", {})
        current = meta.get("batch_counter", 0)
        # If first run, scan existing batch names to find the high-water mark
        if current == 0:
            max_seen = 0
            for rec in state.values():
                if isinstance(rec, dict):
                    b = rec.get("batch", "")
                    if b.startswith("Batch_"):
                        try:
                            n = int(b.split("_")[1])
                            max_seen = max(max_seen, n)
                        except (IndexError, ValueError):
                            pass
            current = max_seen
        first = current + 1
        meta["batch_counter"] = current + count
        _save(state)
    return first


def summary():
    state = _load()
    counts = {}
    for v in state.values():
        if isinstance(v, dict) and "pipeline_status" in v:
            s = v.get("pipeline_status", "unknown")
            counts[s] = counts.get(s, 0) + 1
    return counts
