"""
batch_manager.py -- State management and execution engine for video batches.
"""
from __future__ import annotations

import os
import json
import shutil
import logging
import threading
import sys
import subprocess
from datetime import datetime, date
import collections

# ── Add local pipeline/ to sys.path so we can import shared modules ──────────
_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline")
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

# Import existing pipeline components
import state_manager
import notion_client
import uploader
import zipper

log = logging.getLogger(__name__)

BATCHES_JSON = os.path.join(os.path.dirname(__file__), "batches.json")
_batches_lock = threading.RLock()  # RLock allows same thread to re-acquire (reentrant)

class LogBuffer:
    def __init__(self, maxlen=2000):
        self.buffer = collections.deque(maxlen=maxlen)
        self.lock = threading.Lock()

    def write(self, line):
        with self.lock:
            self.buffer.append(line.rstrip())

    def get_since(self, index):
        with self.lock:
            lines = list(self.buffer)
            if index < 0:
                index = 0
            if index >= len(lines):
                return [], len(lines)
            return lines[index:], len(lines)

    def clear(self):
        with self.lock:
            self.buffer.clear()

# Global log buffer
global_log_buffer = LogBuffer()

class BufferLogHandler(logging.Handler):
    def __init__(self, buffer):
        super().__init__()
        self.buffer = buffer

    def emit(self, record):
        try:
            msg = self.format(record)
            self.buffer.write(msg)
        except Exception:
            self.handleError(record)

# Register logging handler to redirect all process logs to the buffer
handler = BufferLogHandler(global_log_buffer)
handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
logging.getLogger().addHandler(handler)

# State lock status
pipeline_running = False
pipeline_run_thread = None
active_pipeline_process = None
pipeline_paused = False
upload_running = False
upload_paused = False
upload_batch_name = None

# Batch CRUD helper functions
def load_batches() -> dict:
    with _batches_lock:
        if os.path.isfile(BATCHES_JSON):
            try:
                with open(BATCHES_JSON, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.error(f"Error reading batches.json: {e}")
        return {}

def save_batches(batches: dict):
    with _batches_lock:
        tmp_file = BATCHES_JSON + ".tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(batches, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, BATCHES_JSON)
        except Exception as e:
            log.error(f"Error saving batches.json: {e}")
            if os.path.isfile(tmp_file):
                try:
                    os.remove(tmp_file)
                except:
                    pass

def get_active_uploaded_batch() -> str | None:
    """Return the name of a batch that has been uploaded but not yet confirmed (Mark Uploaded).
    This is the only state that blocks new first-review uploads.
    Second reviews (pending_second_review) do NOT block."""
    batches = load_batches()
    for name, b in batches.items():
        if b.get("upload_completed") and b.get("status") == "pending_first_review":
            return name
    return None

def scan_and_register_batches():
    """Scan state.json for batched videos and update batches.json."""
    log.info("Scanning state.json to identify batches...")
    state = state_manager.get_all()
    batches = load_batches()
    
    # Group videos by batch
    grouped = {}
    for page_id, v in state.items():
        if not isinstance(v, dict):
            continue
        batch_name = v.get("batch")
        if batch_name and batch_name.startswith("Batch_"):
            if v.get("pipeline_status") != "failed":
                grouped.setdefault(batch_name, []).append(v)

    # Register each batch
    changed = False
    for batch_name, v_list in grouped.items():
        if batch_name not in batches:
            # Only register if the batch folder or files actually exist on disk
            batch_dir = os.path.join(uploader.BATCHES_DIR, batch_name)
            csv_file = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.csv")
            if not os.path.isdir(batch_dir) and not os.path.isfile(csv_file):
                # Ghost batch — files were deleted. Skip registration.
                continue

            # Check if all videos are uploaded in state.json
            all_uploaded = all(v.get("pipeline_status") == "uploaded" for v in v_list)
            
            # Determine initial status
            if all_uploaded:
                status = "finalized"
            elif os.path.isdir(batch_dir):
                status = "pending_first_review"
            else:
                status = "pending_first_review"
            
            # Extract metadata
            upload_job_id = None
            upload_date = None
            for v in v_list:
                if v.get("job_id"):
                    upload_job_id = v.get("job_id")
                if v.get("upload_date"):
                    upload_date = v.get("upload_date")

            batches[batch_name] = {
                "batch_name": batch_name,
                "status": status,
                "created_at": datetime.now().isoformat(),
                "videos": [
                    {
                        "page_id": v["page_id"],
                        "video_name": v.get("video_name", ""),
                        "age_group": v.get("age_group", ""),
                        "category": v.get("category", ""),
                        "local_file": v.get("local_file", ""),
                        "drive_link": v.get("drive_link", ""),
                        "pipeline_status": v.get("pipeline_status", "")
                    } for v in v_list
                ],
                "upload_job_id": upload_job_id,
                "upload_date": upload_date,
                "finalized_date": None
            }
            changed = True
            log.info(f"Registered new batch: {batch_name} with status {status}")
        else:
            # Update video list and pipeline statuses in batches.json
            batch_record = batches[batch_name]
            updated_videos = []
            for v in v_list:
                updated_videos.append({
                    "page_id": v["page_id"],
                    "video_name": v.get("video_name", ""),
                    "age_group": v.get("age_group", ""),
                    "category": v.get("category", ""),
                    "local_file": v.get("local_file", ""),
                    "drive_link": v.get("drive_link", ""),
                    "pipeline_status": v.get("pipeline_status", "")
                })
            batch_record["videos"] = updated_videos
            
            # Sync metadata if it was updated in state.json
            for v in v_list:
                if v.get("job_id") and not batch_record.get("upload_job_id"):
                    batch_record["upload_job_id"] = v.get("job_id")
                    changed = True
                if v.get("upload_date") and not batch_record.get("upload_date"):
                    batch_record["upload_date"] = v.get("upload_date")
                    changed = True
                    
            if all(v.get("pipeline_status") == "uploaded" for v in v_list) and batch_record["status"] != "finalized":
                batch_record["status"] = "finalized"
                if not batch_record.get("finalized_date"):
                    batch_record["finalized_date"] = datetime.now().isoformat()
                changed = True
                
    if changed:
        save_batches(batches)

def mark_batch_uploaded(batch_name: str, job_id: str | None = None) -> tuple[bool, str]:
    """Confirm a batch as uploaded, moving it to second review.
    Also updates Notion Upload Progress = 'Draft Upload' for each video.
    Second reviews do NOT block other uploads — multiple can exist simultaneously."""
    batches = load_batches()
    if batch_name not in batches:
        return False, f"Batch '{batch_name}' not found."

    b = batches[batch_name]
    if b["status"] == "finalized":
        return False, f"Batch '{batch_name}' is already finalized."

    upload_date = date.today().isoformat()
    b["status"] = "pending_second_review"
    b["upload_job_id"] = job_id or b.get("upload_job_id") or "MANUAL"
    b["upload_date"] = upload_date
    b["upload_completed"] = False  # Clear the blocking flag

    # Update pipeline_status of videos in batches.json (preserve bad status)
    for v in b["videos"]:
        if v["pipeline_status"] != "bad":
            v["pipeline_status"] = "uploaded_pending_final_review"

    save_batches(batches)

    # Update Notion: set Upload Progress = 'Draft Upload' for each good video
    good_videos = [v for v in b["videos"] if v.get("pipeline_status") != "bad"]
    notion_ok = 0
    for v in good_videos:
        page_id = v["page_id"]
        video_name = v["video_name"]
        lang_suffix = ""
        if "___ln_Hi" in video_name:
            lang_suffix = "___ln_Hi"
        elif "___ln_En" in video_name:
            lang_suffix = "___ln_En"
        try:
            success = notion_client.mark_pending_review_in_notion(
                page_id, video_name=video_name, lang_suffix=lang_suffix,
                batch_name=b["upload_job_id"],
            )
            if success:
                notion_ok += 1
                global_log_buffer.write(f"[NOTION] Draft Upload set for: {video_name}")
            else:
                global_log_buffer.write(f"[ERROR] Failed to set Draft Upload for: {video_name}")
        except Exception as e:
            global_log_buffer.write(f"[ERROR] Notion error for {video_name}: {e}")

    log.info(f"[OK] Batch '{batch_name}' marked as Uploaded ({notion_ok}/{len(good_videos)} synced to Notion)")
    return True, f"Batch '{batch_name}' marked as uploaded. {notion_ok}/{len(good_videos)} synced to Notion."

def mark_video_bad(batch_name: str, page_id: str, bad: bool = True, reason: str = "") -> tuple[bool, str]:
    """Toggle a single video's status to 'bad' (or back to 'batched').
    Bad videos are skipped during finalization and reset to pending for redo.
    When marking bad, also updates Notion with Re-do=true and reason."""
    batches = load_batches()
    if batch_name not in batches:
        return False, f"Batch '{batch_name}' not found."

    b = batches[batch_name]
    if b["status"] == "finalized":
        return False, f"Batch '{batch_name}' is already finalized."

    for v in b["videos"]:
        if v["page_id"] == page_id:
            if bad:
                v["pipeline_status"] = "bad"
                v["redo_reason"] = reason
                save_batches(batches)
                # Sync to Notion: Re-do = true, reason for re-do = reason
                notion_success = notion_client.mark_redo_in_notion(page_id, reason)
                if notion_success:
                    global_log_buffer.write(f"[NOTION] Marked '{v['video_name']}' for re-do: {reason}")
                else:
                    global_log_buffer.write(f"[WARNING] Saved locally but Notion sync failed for '{v['video_name']}'")
                # Clear Upload Progress so the video can be re-downloaded
                try:
                    notion_client.clear_upload_progress_in_notion(page_id)
                    global_log_buffer.write(f"[NOTION] Cleared upload progress for: {v['video_name']}")
                except Exception as e:
                    global_log_buffer.write(f"[WARNING] Failed to clear Notion progress for '{v['video_name']}': {e}")
                log.info(f"Video '{v['video_name']}' in {batch_name} marked as bad: {reason}")
                return True, f"'{v['video_name']}' marked as bad — will be skipped during finalization."
            else:
                v["pipeline_status"] = "batched"
                v.pop("redo_reason", None)
                save_batches(batches)
                # Clear Notion: Re-do = false, reason = cleared
                notion_success = notion_client.clear_redo_in_notion(page_id)
                if notion_success:
                    global_log_buffer.write(f"[NOTION] Cleared re-do for '{v['video_name']}'")
                else:
                    global_log_buffer.write(f"[WARNING] Saved locally but Notion clear failed for '{v['video_name']}'")
                log.info(f"Video '{v['video_name']}' in {batch_name} unmarked (restored to batched)")
                return True, f"'{v['video_name']}' restored to batched."

    return False, f"Video with page_id '{page_id}' not found in batch '{batch_name}'."

def run_automated_upload_thread(batch_name: str):
    """Upload → mark uploaded → sync Notion, all in one go."""
    global upload_running, upload_batch_name
    upload_running = True
    upload_batch_name = batch_name
    
    global_log_buffer.write(f"\n============================================================")
    global_log_buffer.write(f"STARTING AUTOMATED UPLOAD FOR BATCH: {batch_name}")
    global_log_buffer.write(f"============================================================\n")
    
    try:
        results = uploader.run_all([batch_name], headless=False)
        job_id = results.get(batch_name)
        if job_id:
            global_log_buffer.write(f"[SUCCESS] Upload complete for {batch_name}. Batch ID: {job_id}")
        else:
            global_log_buffer.write(f"[WARNING] Upload did not return a Batch ID — syncing to Notion anyway.")
            job_id = "MANUAL"

        # Auto-mark as uploaded (no confirmation needed)
        global_log_buffer.write(f"[AUTO] Marking batch as uploaded...")
        upload_date = date.today().isoformat()
        with _batches_lock:
            batches = load_batches()
            if batch_name in batches:
                b = batches[batch_name]
                b["status"] = "pending_second_review"
                b["upload_completed"] = True
                b["upload_job_id"] = job_id
                b["upload_date"] = upload_date
                for v in b["videos"]:
                    if v["pipeline_status"] != "bad":
                        v["pipeline_status"] = "uploaded_pending_final_review"
                save_batches(batches)

        # Sync Notion: set Upload Progress = "Draft Upload" for each video
        b_data = load_batches().get(batch_name, {})
        videos = [v for v in b_data.get("videos", []) if v.get("pipeline_status") != "bad"]
        global_log_buffer.write(f"[NOTION] Setting Upload Progress='Draft Upload' for {len(videos)} videos...")
        notion_ok = 0
        for v in videos:
            page_id = v.get("page_id")
            vname = v.get("video_name", "")
            if page_id:
                lang = "___ln_Hi" if "___ln_Hi" in vname else \
                       "___ln_En" if "___ln_En" in vname else None
                try:
                    ok = notion_client.mark_pending_review_in_notion(
                        page_id, video_name=vname, lang_suffix=lang,
                        batch_name=job_id,
                    )
                    if ok:
                        notion_ok += 1
                        global_log_buffer.write(f"[NOTION] Draft Upload set: {vname}")
                    else:
                        global_log_buffer.write(f"[ERROR] Notion failed for: {vname}")
                except Exception as ne:
                    global_log_buffer.write(f"[ERROR] Notion exception for {vname}: {ne}")
        global_log_buffer.write(f"[NOTION] Done — {notion_ok}/{len(videos)} synced.")
        global_log_buffer.write(f"[DONE] Batch '{batch_name}' uploaded and synced to Notion.")
    except Exception as e:
        log.error(f"Error in automated upload background thread: {e}")
        global_log_buffer.write(f"[EXCEPTION] Automated upload error: {e}")
    finally:
        upload_running = False
        upload_batch_name = None

def start_automated_upload(batch_name: str) -> tuple[bool, str]:
    """Start automated upload in background thread.
    Blocked only if another batch is uploaded but awaiting user confirmation."""
    active = get_active_uploaded_batch()
    if active and active != batch_name:
        return False, f"Cannot upload '{batch_name}': Batch '{active}' was uploaded but not yet confirmed. Click 'Mark Uploaded' on it first."

    batches = load_batches()
    if batch_name not in batches:
        return False, f"Batch '{batch_name}' not found."

    b = batches[batch_name]
    if b["status"] == "finalized":
        return False, f"Batch '{batch_name}' is already finalized."

    # Validate that files exist
    csv_file = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.csv")
    zip_file = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.zip")
    if not os.path.isfile(csv_file):
        return False, f"Missing CSV file for {batch_name} in batches folder."

    # Auto-create ZIP if missing (batch folder with MP4s exists but wasn't zipped)
    if not os.path.isfile(zip_file):
        global_log_buffer.write(f"[ZIP] ZIP missing for {batch_name} — creating automatically...")
        zip_result = zipper.zip_batch(batch_name)
        if not zip_result:
            return False, f"Failed to create ZIP for {batch_name}. Check that the batch folder contains MP4 files."

    # Run in thread
    t = threading.Thread(target=run_automated_upload_thread, args=(batch_name,))
    t.daemon = True
    t.start()
    return True, f"Automated upload started for {batch_name}. Monitor the terminal below for logs."

def finalize_batch(batch_name: str) -> tuple[bool, str]:
    """Real Finalization Step: Sync to Notion, update state.json, and delete local files."""
    batches = load_batches()
    if batch_name not in batches:
        return False, f"Batch '{batch_name}' not found."

    b = batches[batch_name]
    if b["status"] == "finalized":
        return True, f"Batch '{batch_name}' is already finalized."

    upload_date = b.get("upload_date") or date.today().isoformat()
    job_id = b.get("upload_job_id") or "MANUAL"

    log.info(f"Starting finalization for batch {batch_name}...")
    global_log_buffer.write(f"\n[FINALIZING] Syncing batch '{batch_name}' ({len(b['videos'])} videos) to Notion...")

    success_count = 0
    fail_count = 0
    bad_count = 0

    # Separate bad videos from good ones
    good_videos = [v for v in b["videos"] if v.get("pipeline_status") != "bad"]
    bad_videos = [v for v in b["videos"] if v.get("pipeline_status") == "bad"]

    # Reset bad videos to pending so they get re-processed in a future pipeline run
    for v in bad_videos:
        page_id = v["page_id"]
        video_name = v["video_name"]
        state_manager.upsert(page_id, pipeline_status="pending", batch="", local_file="")
        # Clear Upload Progress in Notion so the video can be re-downloaded
        try:
            notion_client.clear_upload_progress_in_notion(page_id)
        except Exception as e:
            global_log_buffer.write(f"[WARNING] Failed to clear Notion progress for '{video_name}': {e}")
        global_log_buffer.write(f"[SKIP] Bad video '{video_name}' — reset to pending for redo.")
        bad_count += 1

    # 1. Update state.json first, then set Upload Progress='Draft Upload' + title in Notion
    #    Upload checkbox is NOT checked here — that's done from the Reviews tab.
    for v in good_videos:
        page_id = v["page_id"]
        video_name = v["video_name"]
        
        # Extract lang_suffix from the video_name (e.g., ___ln_Hi or ___ln_En)
        lang_suffix = ""
        if "___ln_Hi" in video_name:
            lang_suffix = "___ln_Hi"
        elif "___ln_En" in video_name:
            lang_suffix = "___ln_En"

        # Build the correct state key (matches how batcher.py stored it)
        state_key = page_id + lang_suffix if lang_suffix else page_id

        # Mark state as uploaded
        state_manager.mark_uploaded(state_key, job_id, upload_date)
        v["pipeline_status"] = "uploaded"

        global_log_buffer.write(f"[NOTION] Setting Upload Progress='Draft Upload' + title: {video_name}...")
        notion_success = notion_client.mark_pending_review_in_notion(
            page_id,
            video_name=video_name,
            lang_suffix=lang_suffix,
            batch_name=batch_name,
        )
        
        if notion_success:
            success_count += 1
        else:
            global_log_buffer.write(f"[ERROR] Failed to update Notion for {video_name} (ID: {page_id})")
            fail_count += 1

    # 2. Delete local files
    global_log_buffer.write(f"[CLEANUP] Deleting local files for batch {batch_name}...")
    for v in b["videos"]:
        local_file = v.get("local_file")
        if local_file and os.path.isfile(local_file):
            try:
                os.remove(local_file)
                log.info(f"Deleted local download: {local_file}")
            except Exception as e:
                log.error(f"Failed to delete download {local_file}: {e}")

    # Delete batch directory
    batch_dir = os.path.join(uploader.BATCHES_DIR, batch_name)
    if os.path.isdir(batch_dir):
        try:
            shutil.rmtree(batch_dir)
            log.info(f"Deleted batch directory: {batch_dir}")
        except Exception as e:
            log.error(f"Failed to delete batch directory {batch_dir}: {e}")

    # Delete CSV and ZIP
    csv_file = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.csv")
    zip_file = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.zip")
    for fpath in (csv_file, zip_file):
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
                log.info(f"Deleted batch file: {fpath}")
            except Exception as e:
                log.error(f"Failed to delete file {fpath}: {e}")

    # Update status in batches.json
    b["status"] = "finalized"
    b["finalized_date"] = datetime.now().isoformat()
    save_batches(batches)

    bad_msg = f", {bad_count} bad (reset to pending)" if bad_count else ""
    global_log_buffer.write(f"[SUCCESS] Finalization complete for '{batch_name}': {success_count} synced, {fail_count} failed{bad_msg}. Local files cleaned up.")
    return True, f"Batch '{batch_name}' finalized: {success_count} uploaded, {fail_count} failed{bad_msg}."

# Pipeline background execution
def run_pipeline_thread(batch_only: bool = False, max_batches: int = None):
    global pipeline_running, active_pipeline_process
    log_mode = "BATCH-ONLY MODE (processing existing downloads)" if batch_only else "NORMAL MODE (fetching new from Notion)"
    batch_limit_msg = f", max {max_batches} batches" if max_batches else ""
    global_log_buffer.write(f"\n============================================================")
    global_log_buffer.write(f"STARTING PIPELINE RUN: {log_mode}{batch_limit_msg}")
    global_log_buffer.write(f"============================================================\n")

    try:
        # Run pipeline.py as a subprocess to capture console logs
        # Using sys.executable to run inside the same virtual environment!
        cmd = [sys.executable, "-u", "pipeline.py", "--skip-upload"]
        if batch_only:
            cmd.append("--batch-only")
        if max_batches and max_batches > 0:
            cmd.extend(["--max-batches", str(max_batches)])

        # Force unbuffered output so logs appear in real-time
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
            
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=_PIPELINE_DIR,
            env=env
        )
        active_pipeline_process = proc
        
        # Read stdout in real time
        for line in proc.stdout:
            global_log_buffer.write(line.strip())
            
        proc.wait()
        global_log_buffer.write(f"\n[PIPELINE] Execution finished. Exit code: {proc.returncode}")
        
        # Scan and register any new batches generated
        scan_and_register_batches()
        
    except Exception as e:
        log.error(f"Error running pipeline subprocess: {e}")
        global_log_buffer.write(f"[EXCEPTION] Subprocess failed: {e}")
    finally:
        pipeline_running = False
        active_pipeline_process = None
        pipeline_paused = False

def start_pipeline_batching(batch_only: bool = False, max_batches: int = None) -> tuple[bool, str]:
    global pipeline_running
    global pipeline_run_thread
    
    if pipeline_running:
        return False, "Pipeline is already running in the background."

    pipeline_running = True
    pipeline_run_thread = threading.Thread(target=run_pipeline_thread, args=(batch_only, max_batches))
    pipeline_run_thread.daemon = True
    pipeline_run_thread.start()
    return True, "Pipeline started in the background. Monitor logs below."

def stop_pipeline_batching() -> tuple[bool, str]:
    global active_pipeline_process, pipeline_running, pipeline_paused
    if not pipeline_running or not active_pipeline_process:
        return False, "Pipeline batcher is not currently running."
    
    try:
        global_log_buffer.write("[ABORT] Stopping pipeline batcher subprocess...")
        # If suspended, resume first so it can terminate properly
        if pipeline_paused:
            PROCESS_SUSPEND_RESUME = 0x0800
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, active_pipeline_process.pid)
            if handle:
                ctypes.windll.ntdll.NtResumeProcess(handle)
                ctypes.windll.kernel32.CloseHandle(handle)
            pipeline_paused = False
            
        active_pipeline_process.terminate()
        try:
            active_pipeline_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            active_pipeline_process.kill()
            active_pipeline_process.wait()
        global_log_buffer.write("[ABORTED] Pipeline batcher stopped by user.")
    except Exception as e:
        log.error(f"Error stopping pipeline batcher: {e}")
        return False, f"Failed to stop pipeline batcher: {e}"
    finally:
        pipeline_running = False
        active_pipeline_process = None
        pipeline_paused = False
    return True, "Pipeline batcher successfully stopped."

def pause_pipeline_batching() -> tuple[bool, str]:
    global active_pipeline_process, pipeline_running, pipeline_paused
    if not pipeline_running or not active_pipeline_process:
        return False, "Pipeline batcher is not currently running."
    if pipeline_paused:
        return False, "Pipeline batcher is already paused."
        
    try:
        global_log_buffer.write("[PAUSE] Pausing pipeline batcher subprocess...")
        PROCESS_SUSPEND_RESUME = 0x0800
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, active_pipeline_process.pid)
        if handle:
            ret = ctypes.windll.ntdll.NtSuspendProcess(handle)
            ctypes.windll.kernel32.CloseHandle(handle)
            if ret == 0:
                pipeline_paused = True
                global_log_buffer.write("[PAUSED] Pipeline batcher suspended. Click Resume to continue.")
                return True, "Pipeline batcher successfully paused."
            else:
                return False, f"NtSuspendProcess failed with code {ret}."
        else:
            return False, "Failed to open process handle."
    except Exception as e:
        log.error(f"Error pausing pipeline batcher: {e}")
        return False, f"Failed to pause pipeline batcher: {e}"

def resume_pipeline_batching() -> tuple[bool, str]:
    global active_pipeline_process, pipeline_running, pipeline_paused
    if not pipeline_running or not active_pipeline_process:
        return False, "Pipeline batcher is not currently running."
    if not pipeline_paused:
        return False, "Pipeline batcher is not currently paused."
        
    try:
        global_log_buffer.write("[RESUME] Resuming pipeline batcher subprocess...")
        PROCESS_SUSPEND_RESUME = 0x0800
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, active_pipeline_process.pid)
        if handle:
            ret = ctypes.windll.ntdll.NtResumeProcess(handle)
            ctypes.windll.kernel32.CloseHandle(handle)
            if ret == 0:
                pipeline_paused = False
                global_log_buffer.write("[RESUMED] Pipeline batcher resumed.")
                return True, "Pipeline batcher successfully resumed."
            else:
                return False, f"NtResumeProcess failed with code {ret}."
        else:
            return False, "Failed to open process handle."
    except Exception as e:
        log.error(f"Error resuming pipeline batcher: {e}")
        return False, f"Failed to resume pipeline batcher: {e}"

def stop_automated_upload() -> tuple[bool, str]:
    global upload_running, upload_batch_name, upload_paused
    if not upload_running:
        return False, "Automated upload is not currently running."
    
    try:
        global_log_buffer.write("[ABORT] Stopping Selenium automated upload...")
        # Unblock event so thread wakes up and quits
        uploader.upload_resume_event.set()
        uploader.abort()
        global_log_buffer.write("[ABORTED] Selenium automated upload stopped by user.")
    except Exception as e:
        log.error(f"Error stopping automated upload: {e}")
        return False, f"Failed to stop automated upload: {e}"
    finally:
        upload_running = False
        upload_batch_name = None
        upload_paused = False
    return True, "Automated upload successfully stopped."

def pause_automated_upload() -> tuple[bool, str]:
    global upload_running, upload_paused
    if not upload_running:
        return False, "Automated upload is not currently running."
    if upload_paused:
        return False, "Automated upload is already paused."
        
    try:
        global_log_buffer.write("[PAUSE] Pausing Selenium automated upload...")
        uploader.upload_resume_event.clear()
        upload_paused = True
        global_log_buffer.write("[PAUSED] Selenium automated upload paused. Click Resume to continue.")
        return True, "Automated upload successfully paused."
    except Exception as e:
        log.error(f"Error pausing automated upload: {e}")
        return False, f"Failed to pause automated upload: {e}"

def resume_automated_upload() -> tuple[bool, str]:
    global upload_running, upload_paused
    if not upload_running:
        return False, "Automated upload is not currently running."
    if not upload_paused:
        return False, "Automated upload is not currently paused."
        
    try:
        global_log_buffer.write("[RESUME] Resuming Selenium automated upload...")
        uploader.upload_resume_event.set()
        upload_paused = False
        global_log_buffer.write("[RESUMED] Selenium automated upload resumed.")
        return True, "Automated upload successfully resumed."
    except Exception as e:
        log.error(f"Error resuming automated upload: {e}")
        return False, f"Failed to resume automated upload: {e}"


# ── Cross-computer review workflow ────────────────────────────────────────────

def get_pending_reviews() -> list[dict]:
    """Query Notion for pages with Status='Uploaded' and Upload unchecked."""
    try:
        return notion_client.query_pending_review()
    except Exception as e:
        log.error(f"Failed to query pending reviews: {e}")
        return []


def finalize_review(page_id: str) -> tuple[bool, str]:
    """Finalize a single Notion page: check Upload box + set Upload Date."""
    try:
        success = notion_client.finalize_in_notion(page_id)
        if success:
            return True, f"Page {page_id} finalized successfully."
        else:
            return False, f"Failed to finalize page {page_id}."
    except Exception as e:
        log.error(f"Error finalizing {page_id}: {e}")
        return False, f"Error finalizing page: {e}"


def finalize_all_reviews() -> tuple[int, int, str]:
    """Finalize ALL pending review pages at once."""
    pages = get_pending_reviews()
    if not pages:
        return 0, 0, "No pending reviews found."

    success = 0
    failed = 0
    for p in pages:
        ok, msg = finalize_review(p["page_id"])
        if ok:
            success += 1
        else:
            failed += 1
            log.warning(f"Finalize failed for {p['video_name']}: {msg}")

    return success, failed, f"Finalized {success}/{success + failed} pages."

