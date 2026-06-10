"""
pipeline.py -- Main orchestrator for the BabyBillion Notion upload pipeline.

Stages:
  1. Fetch   -- Query Notion API for "Ready to Upload" videos
  2. Download -- Download each video from Google Drive via gdown
  3. Batch    -- Group into sub-70MB batches, write admin CSVs
  4. Zip      -- Create ZIP archives
  5. Upload   -- Selenium-upload each batch to admin.babybillion.in
  6. Track    -- Update state.json AND mark each video as uploaded in Notion

Usage:
    python pipeline.py [options]

Options:
    --dry-run         Show what would be processed, don't download/upload
    --skip-download   Skip downloads (use already-downloaded files)
    --skip-upload     Stop after zipping (don't upload)
    --headless        Run Chrome headless
    --batch-only      Only batch + zip what's already in downloads/
    --status          Print pipeline state summary and exit
"""
from __future__ import annotations

import os
import sys
import time
import argparse
import logging
from datetime import date, datetime

# ── Logging setup (must happen before importing modules that use it) ───────────
os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
log_path = os.path.join(
    os.path.dirname(__file__), "logs",
    f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Local imports ──────────────────────────────────────────────────────────────
from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID,
    BB_USERNAME, BB_PASSWORD, DOWNLOADS_DIR, BATCHES_DIR,
    ADMIN_UPLOAD_URL,
)
import state_manager as sm
import notion_client as nc
import sanity_checker
import downloader
import compressor
import batcher
import zipper
import uploader
from dedup_utils import normalize_video_key, normalize_age, build_uploaded_keys_from_state


def _state_key(v: dict) -> str:
    """Composite state key: page_id + lang_suffix.
    Hindi and English variants of the same Notion page are tracked independently."""
    return v["page_id"] + v.get("lang_suffix", "")


def _all_page_variants_uploaded(page_id: str) -> bool:
    """Check if ALL language variants for a Notion page are uploaded.

    Scans state.json for all records with the same page_id.
    Returns True only when every sibling has pipeline_status == 'uploaded'.
    If only one variant exists, returns True as soon as it's uploaded.
    """
    state = sm.get_all()
    siblings = [
        rec for rec in state.values()
        if isinstance(rec, dict) and rec.get("page_id") == page_id
    ]
    if not siblings:
        return True  # no records found — safe to mark
    return all(rec.get("pipeline_status") == "uploaded" for rec in siblings)


# ════════════════════════════════════════════════════════════════════════════════
#  STAGE 1 -- Fetch from Notion
# ════════════════════════════════════════════════════════════════════════════════

def stage_fetch(dry_run: bool = False) -> list[dict]:
    log.info("\n" + "="*60)
    log.info("STAGE 1: Fetching from Notion …")
    log.info("="*60)

    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        log.error(
            "Notion credentials not set!\n"
            "Run:\n"
            "  $env:NOTION_TOKEN       = 'secret_xxxxx'\n"
            "  $env:NOTION_DATABASE_ID = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'\n"
            "Or edit config.py"
        )
        sys.exit(1)

    if not nc.validate_connection():
        sys.exit(1)

    # ── Pre-flight: resolve any unsynced Notion writebacks from last run ──────
    #    If the previous run uploaded videos but couldn't update Notion (API was
    #    down), the page IDs were saved to notion_unsynced.json. We MUST resolve
    #    these before fetching new videos, otherwise they'd be fetched again.
    import json as _json
    unsynced_path = os.path.join(os.path.dirname(__file__), "notion_unsynced.json")
    if os.path.isfile(unsynced_path):
        try:
            with open(unsynced_path, "r") as f:
                unsynced_pids = _json.load(f)
        except Exception:
            unsynced_pids = []

        if unsynced_pids:
            log.info(f"\n  Found {len(unsynced_pids)} unsynced Notion update(s) from last run.")
            log.info(f"  Resolving before fetching new videos...")
            resolved = []
            for pid in unsynced_pids:
                try:
                    today_str = date.today().isoformat()
                    if nc.mark_uploaded_in_notion(pid, today_str):
                        log.info(f"    [OK] Resolved: {pid}")
                        resolved.append(pid)
                    else:
                        log.warning(f"    [FAIL] Still can't update: {pid}")
                except Exception as e:
                    log.warning(f"    [FAIL] {pid}: {e}")

            remaining = [p for p in unsynced_pids if p not in resolved]
            if remaining:
                # Still can't update — save back and abort
                with open(unsynced_path, "w") as f:
                    _json.dump(remaining, f, indent=2)
                log.error(
                    f"\n  ⚠️  {len(remaining)} page(s) STILL unsynced in Notion.\n"
                    f"  Cannot safely fetch new videos — they might be duplicates.\n"
                    f"  Fix your internet / Notion access and run again."
                )
                sys.exit(1)
            else:
                # All resolved — delete the file
                os.remove(unsynced_path)
                log.info(f"  All unsynced updates resolved. Proceeding normally.\n")

    videos = nc.query_ready_to_upload()

    # ── Guard 1: Skip already-uploaded ────────────────────────────────────────
    new_videos = [v for v in videos if not sm.is_done(_state_key(v))]
    skipped_done = len(videos) - len(new_videos)

    # ── Guard 2: Skip already in-progress (downloaded/batched/zipped/uploading)
    #    This prevents re-runs from re-batching videos that got stuck.
    IN_PROGRESS = {"downloading", "downloaded", "batched", "zipped", "uploading"}
    ready_videos = []
    skipped_inprogress = 0
    for v in new_videos:
        rec = sm.get(_state_key(v))
        if rec and rec.get("pipeline_status") in IN_PROGRESS:
            log.info(
                f"  [SKIP] Already in-progress ({rec['pipeline_status']}): "
                f"{v['video_name']} [page={v['page_id'][:12]}…]"
            )
            skipped_inprogress += 1
            continue
        ready_videos.append(v)

    # ── Guard 3: Deduplicate by normalised filename ───────────────────────────
    #    Two Notion pages with the same video name (e.g. "Calf (Baby Cow)" in
    #    both 0-3 and 3-6 age groups) produce the same MP4 filename, which
    #    causes batch CSV / zip collisions.  Keep only the first occurrence per
    #    sanitised name+age combo; log duplicates so they can be investigated.

    seen_keys: dict[tuple, dict] = {}  # (norm_name, age) -> first video dict
    deduped_videos = []
    skipped_dupes  = 0
    for v in ready_videos:
        key = normalize_video_key(v["video_name"], v.get("age_group", ""))
        if key in seen_keys:
            first = seen_keys[key]
            log.warning(
                f"  [DUPE] Skipping duplicate video name '{v['video_name']}' "
                f"(age={v.get('age_group','?')}, page={v['page_id'][:12]}…) "
                f"— already queued from page={first['page_id'][:12]}…"
            )
            skipped_dupes += 1
            continue
        seen_keys[key] = v
        deduped_videos.append(v)

    # ── Guard 4: Cross-check against ALL previously-uploaded videos ───────
    #    Even if the page_id is new, the content (name+age) may already
    #    exist from a different Notion page that was uploaded in a prior run.
    #    Uses the unified normalize_video_key() to guarantee consistent matching.
    state_all = sm.get_all()
    uploaded_keys = build_uploaded_keys_from_state(state_all)

    safe_videos = []
    skipped_already_uploaded = 0
    for v in deduped_videos:
        key = normalize_video_key(v["video_name"], v.get("age_group", ""))
        if key in uploaded_keys:
            log.warning(
                f"  [DUPE-UPLOAD] Skipping '{v['video_name']}' "
                f"(age={v.get('age_group','?')}, page={v['page_id'][:12]}…) "
                f"— content already uploaded in a prior run"
            )
            skipped_already_uploaded += 1
            continue
        safe_videos.append(v)
    deduped_videos = safe_videos

    log.info(f"Found {len(videos)} ready-to-upload videos.")
    log.info(f"  {skipped_done} already uploaded (in state.json) -- skipping.")
    log.info(f"  {skipped_inprogress} already in-progress -- skipping.")
    log.info(f"  {skipped_dupes} duplicate video names -- skipping.")
    log.info(f"  {skipped_already_uploaded} content already uploaded (name+age match) -- skipping.")
    log.info(f"  {len(deduped_videos)} new videos to process (pre-sanity-check).")

    # ── Guard 5: Sanity check — validate fields before entering pipeline ──────
    #    Videos that fail are marked as "Failed to upload" in Notion and
    #    removed from the pipeline.  They are NEVER downloaded or batched.
    sane_videos, failed_videos = sanity_checker.run(deduped_videos, mark_notion=True)

    if failed_videos:
        log.warning(
            f"  {len(failed_videos)} video(s) FAILED sanity check "
            f"and have been marked 'Failed to upload' in Notion."
        )

    log.info(f"  {len(sane_videos)} videos passed sanity check — entering pipeline.")

    for v in sane_videos:
        sm.upsert(_state_key(v),
                  page_id=v["page_id"],
                  video_name=v["video_name"],
                  age_group=normalize_age(v["age_group"]),
                  category=v["category"],
                  drive_link=v["drive_link"],
                  lang_suffix=v.get("lang_suffix", ""),
                  pipeline_status="pending")

    if dry_run:
        log.info("\n-- DRY RUN: would process --")
        for v in sane_videos:
            log.info(f"  {v['video_name']} | {v['age_group']} | {v['category']} | {v['drive_link'][:60]}")
        if failed_videos:
            log.info("\n-- DRY RUN: would FAIL (sanity check) --")
            for v in failed_videos:
                log.info(f"  ✗ {v['video_name']} | {v['age_group']} | {v['category']}")
        sys.exit(0)

    return sane_videos


# ════════════════════════════════════════════════════════════════════════════════
#  STAGE 2 -- Download
# ════════════════════════════════════════════════════════════════════════════════

def stage_download(videos: list[dict]) -> list[dict]:
    log.info("\n" + "="*60)
    log.info("STAGE 2: Downloading videos …")
    log.info("="*60)

    downloaded = []
    for i, v in enumerate(videos, 1):
        log.info(f"\n[{i}/{len(videos)}] {v['video_name']}")

        if sm.is_downloaded(_state_key(v)):
            rec = sm.get(_state_key(v))
            local_file = rec.get("local_file", "")
            if local_file and os.path.isfile(local_file):
                log.info(f"  [SKIP] Already downloaded: {local_file}")
                v["local_file"] = local_file
                downloaded.append(v)
                continue

        sm.set_status(_state_key(v), "downloading")
        local_file = downloader.download_video(
            _state_key(v), v["video_name"], v["drive_link"]
        )

        if local_file:
            sm.mark_downloaded(_state_key(v), local_file)
            v["local_file"] = local_file
            downloaded.append(v)
        else:
            sm.mark_failed(_state_key(v), "download_failed")
            log.error(f"  [FAIL] Download failed: {v['video_name']}")

        time.sleep(1)  # brief pause between downloads

    log.info(f"\nDownloaded: {len(downloaded)}/{len(videos)} videos.")
    return downloaded


# ════════════════════════════════════════════════════════════════════════════════
#  STAGE 2.5 -- Compress
# ════════════════════════════════════════════════════════════════════════════════

def stage_compress(downloaded: list[dict]) -> list[dict]:
    log.info("\n" + "="*60)
    log.info("STAGE 2.5: Compressing videos to <20 MB …")
    log.info("="*60)
    return compressor.compress_all(downloaded)


# ════════════════════════════════════════════════════════════════════════════════
#  STAGE 3 -- Batch + CSV
# ════════════════════════════════════════════════════════════════════════════════

def stage_batch(downloaded: list[dict]) -> list[str]:
    log.info("\n" + "="*60)
    log.info("STAGE 3: Batching into <70MB groups …")
    log.info("="*60)
    return batcher.run(downloaded)


# ════════════════════════════════════════════════════════════════════════════════
#  STAGE 4 -- Zip
# ════════════════════════════════════════════════════════════════════════════════

def stage_zip(batch_names: list[str]) -> dict[str, str]:
    log.info("\n" + "="*60)
    log.info("STAGE 4: Creating ZIP archives …")
    log.info("="*60)
    return zipper.zip_all(batch_names)


# ════════════════════════════════════════════════════════════════════════════════
#  STAGE 5 -- Upload
# ════════════════════════════════════════════════════════════════════════════════

def stage_upload(batch_names: list[str], headless: bool = False) -> dict[str, str | None]:
    log.info("\n" + "="*60)
    log.info("STAGE 5: Uploading to BabyBillion Admin …")
    log.info("="*60)

    if not BB_USERNAME or not BB_PASSWORD:
        log.error(
            "Admin credentials not set!\n"
            "Run:\n"
            "  $env:BB_USERNAME = 'your_username'\n"
            "  $env:BB_PASSWORD = 'your_password'"
        )
        sys.exit(1)

    # ── Safety gate: skip any batch that contains already-uploaded videos ─────
    # Pull state and build batch -> page_id list
    state = sm.get_all()
    batch_to_pids: dict[str, list[str]] = {}
    for pid, rec in state.items():
        b = rec.get("batch")
        if b:
            batch_to_pids.setdefault(b, []).append(pid)

    safe_batches = []
    for bname in batch_names:
        pids = batch_to_pids.get(bname, [])
        already_done = [p for p in pids if sm.is_done(p)]
        if already_done:
            log.warning(
                f"  [WARN] SKIP {bname}: {len(already_done)}/{len(pids)} video(s) "
                f"already marked uploaded in state.json -- will not re-upload."
            )
            continue
        safe_batches.append(bname)

    if not safe_batches:
        log.info("All batches are already uploaded. Nothing to do.")
        return {}

    log.info(f"  Uploading {len(safe_batches)} batch(es): {safe_batches}")
    return uploader.run_all(safe_batches, headless=headless)


# ════════════════════════════════════════════════════════════════════════════════
#  STAGE 6 -- Track & Notion write-back
# ════════════════════════════════════════════════════════════════════════════════

def stage_track(batch_job_map: dict[str, str | None], all_videos: list[dict], auto_finalize: bool = False):
    """
    For each successfully uploaded batch:
      - Update state.json for all videos in that batch
      - Call Notion API to mark each video as uploaded
    """
    log.info("\n" + "="*60)
    log.info("STAGE 6: Updating state + Notion …")
    log.info("="*60)

    today = date.today().isoformat()

    # Build page_id -> video mapping
    pid_to_video = {v["page_id"]: v for v in all_videos}

    # Build batch -> page_ids mapping from state
    state = sm.get_all()
    batch_to_pids: dict[str, list[str]] = {}
    for pid, rec in state.items():
        b = rec.get("batch")
        if b:
            batch_to_pids.setdefault(b, []).append(pid)

    notion_updated = 0
    notion_failed  = 0

    for batch_name, job_id in batch_job_map.items():
        if not job_id:
            log.warning(f"  [WARN] {batch_name}: no job_id -- marking as failed")
            for pid in batch_to_pids.get(batch_name, []):
                sm.mark_failed(pid, "upload_no_job_id")
            continue

        log.info(f"  {batch_name}: job_id={job_id}")
        page_ids = batch_to_pids.get(batch_name, [])

        for state_key in page_ids:
            # Update state.json
            sm.mark_uploaded(state_key, job_id, today)

            # Use real page_id (not composite key) for Notion API
            rec = sm.get(state_key)
            real_page_id = rec.get("page_id", state_key) if rec else state_key

            # Update Notion
            log.info(f"    Notifying Notion for page {real_page_id} …")
            video_name = rec.get("video_name", "") if rec else ""
            lang_suffix = rec.get("lang_suffix", "") if rec else ""
            if auto_finalize:
                # Old single-machine mode: check Upload box directly
                all_done = _all_page_variants_uploaded(real_page_id)
                success = nc.mark_uploaded_in_notion(
                    real_page_id, today,
                    video_name=video_name,
                    lang_suffix=lang_suffix,
                    check_upload=all_done,
                )
            else:
                # Cross-computer mode: set pending review (reviewer finalizes later)
                success = nc.mark_pending_review_in_notion(
                    real_page_id,
                    video_name=video_name,
                    lang_suffix=lang_suffix,
                )
            if success:
                notion_updated += 1
            else:
                notion_failed += 1
                log.warning(f"    [WARN] Notion update failed for {real_page_id} -- logged in state.json")

    log.info(f"\nNotion updated: {notion_updated} pages")
    if notion_failed:
        log.warning(f"Notion failed:  {notion_failed} pages (check logs -- state.json still updated)")


# ════════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════════

def run_parallel_pipeline(all_videos: list[dict], headless: bool = False, skip_upload: bool = False, auto_finalize: bool = False):
    """
    3-stage concurrent pipeline:
      [Download x3 threads] → compress_q → [Compress x1] → batch_q → [Batch/Zip/Upload x1]

    Downloads run in parallel (I/O bound).
    Compression runs as soon as each video lands (CPU bound, single thread).
    Batching/zipping/uploading fires as soon as a batch fills up — no waiting.
    """
    import queue
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from config import MAX_BATCH_BYTES

    DONE      = object()   # sentinel
    compress_q = queue.Queue(maxsize=6)   # slight backpressure so downloads don't race far ahead
    batch_q    = queue.Queue()
    today      = date.today().isoformat()
    batch_job_map: dict[str, str | None] = {}
    # Track pages where Notion writeback failed so we can retry synchronously
    _notion_retry_queue: list[str] = []   # page_ids that need a sync retry
    _notion_retry_lock = threading.Lock()
    lock       = threading.Lock()         # for shared log lines

    # ── A: Download one video (runs inside ThreadPoolExecutor) ────────────────
    def download_one(v: dict):
        pid = _state_key(v)
        if sm.is_downloaded(pid):
            rec = sm.get(pid)
            lf  = rec.get("local_file", "") if rec else ""
            if lf and os.path.isfile(lf):
                with lock:
                    log.info(f"  [SKIP] Already downloaded: {v['video_name']}")
                v["local_file"] = lf
                compress_q.put(v)
                return
        sm.set_status(pid, "downloading")
        # Retry downloads up to 3 times with exponential backoff
        max_dl_retries = 3
        lf = None
        for dl_attempt in range(1, max_dl_retries + 1):
            lf = downloader.download_video(pid, v["video_name"], v["drive_link"])
            if lf:
                break
            if dl_attempt < max_dl_retries:
                wait = 5 * (2 ** (dl_attempt - 1))  # 5s, 10s
                with lock:
                    log.warning(f"  [RETRY] Download attempt {dl_attempt}/{max_dl_retries} failed for {v['video_name']}, retrying in {wait}s...")
                time.sleep(wait)
        if lf:
            sm.mark_downloaded(pid, lf)
            v["local_file"] = lf
            compress_q.put(v)
        else:
            sm.mark_failed(pid, "download_failed")

    # ── B: Compress worker (single thread — CPU bound) ────────────────────────
    def compress_worker():
        while True:
            item = compress_q.get()
            if item is DONE:
                batch_q.put(DONE)
                return
            v = item
            compressor.compress(_state_key(v), v["video_name"], v["local_file"])
            batch_q.put(v)

    # ── C: Batch / zip / upload worker (single thread — Selenium) ────────────
    def batch_upload_worker():
        driver       = None
        logged_in    = False
        pending      : list[dict] = []
        pending_size : int        = 0

        def flush(videos: list[dict]):
            nonlocal driver, logged_in, batch_job_map
            if not videos:
                return

            log.info(f"\n{'='*60}")
            log.info(f"  Flushing batch: {len(videos)} video(s)")

            # Batch + CSV
            batch_names = batcher.run(videos)
            if not batch_names:
                log.error("  Batching failed — skipping flush")
                return

            # Zip
            zipped = zipper.zip_all(batch_names)
            if not zipped:
                log.error("  Zipping failed — skipping flush")
                return

            if skip_upload:
                log.info(f"  --skip-upload: batches ready {batch_names}")
                return

            # ── Helper: ensure we have a working Selenium driver ────────────
            def _ensure_driver():
                nonlocal driver, logged_in
                MAX_DRIVER_RETRIES = 5
                for attempt in range(1, MAX_DRIVER_RETRIES + 1):
                    try:
                        if driver is None:
                            driver = uploader.build_driver(headless=headless)
                        # Quick health-check: can we reach the page?
                        driver.get(ADMIN_UPLOAD_URL)
                        time.sleep(2)
                        logged_in = uploader.login(driver)
                        if logged_in:
                            return True
                    except Exception as e:
                        log.warning(f"  [DRIVER] Attempt {attempt}/{MAX_DRIVER_RETRIES} failed: {e}")
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = None
                    # Wait before retry (exponential backoff: 10s, 20s, 40s, 80s, 160s)
                    wait = 10 * (2 ** (attempt - 1))
                    log.info(f"  [DRIVER] Waiting {wait}s before retry (network may be down)...")
                    time.sleep(wait)
                log.error(f"  [DRIVER] All {MAX_DRIVER_RETRIES} driver recovery attempts failed")
                return False

            if not _ensure_driver():
                log.error("  Login failed — cannot upload this batch")
                for v in videos:
                    sm.mark_failed(_state_key(v), "login_failed")
                return

            # Upload each batch — Notion updates run in background so we
            # can start the next upload immediately after getting a job_id.
            post_upload_threads: list[threading.Thread] = []

            def _post_upload_work(bname_: str, job_id_: str, pids_: list[str]):
                """Background: update Notion + cleanup (non-blocking)."""
                for state_key in pids_:
                    verified_rec = sm.get(state_key)
                    if not verified_rec or verified_rec.get("pipeline_status") != "uploaded":
                        log.error(
                            f"    [SKIP NOTION] state.json NOT confirmed 'uploaded' for {state_key} "
                            f"-- will NOT mark Notion to avoid false positive"
                        )
                        continue
                    # Use real page_id (not composite key) for Notion API
                    real_page_id = verified_rec.get("page_id", state_key)
                    try:
                        video_name = verified_rec.get("video_name", "")
                        lang_suffix = verified_rec.get("lang_suffix", "")
                        if auto_finalize:
                            all_done = _all_page_variants_uploaded(real_page_id)
                            success = nc.mark_uploaded_in_notion(
                                real_page_id, today,
                                video_name=video_name,
                                lang_suffix=lang_suffix,
                                check_upload=all_done,
                            )
                        else:
                            success = nc.mark_pending_review_in_notion(
                                real_page_id,
                                video_name=video_name,
                                lang_suffix=lang_suffix,
                            )
                        if not success:
                            raise RuntimeError("Notion writeback returned False")
                    except Exception as notion_err:
                        log.warning(
                            f"    [WARN] Notion update failed for {pid}: {notion_err} "
                            f"-- queuing for synchronous retry before pipeline exits"
                        )
                        with _notion_retry_lock:
                            _notion_retry_queue.append(real_page_id)
                    local_file = verified_rec.get("local_file", "")
                    if local_file and os.path.isfile(local_file):
                        try:
                            os.remove(local_file)
                            log.info(f"    [CLEANUP] Deleted local file: {local_file}")
                        except Exception as del_err:
                            log.warning(f"    [WARN] Could not delete local file {local_file}: {del_err}")
                    elif local_file:
                        log.info(f"    [CLEANUP] Local file already gone: {local_file}")
                # Clean up batch artifacts (dir, CSV, ZIP)
                try:
                    import shutil as _shutil
                    batch_dir = os.path.join(BATCHES_DIR, bname_)
                    if os.path.isdir(batch_dir):
                        _shutil.rmtree(batch_dir)
                    for ext in (".csv", ".zip"):
                        bf = os.path.join(BATCHES_DIR, f"{bname_}{ext}")
                        if os.path.isfile(bf):
                            os.remove(bf)
                    log.info(f"    [CLEANUP] Batch artifacts removed: {bname_}")
                except Exception as cleanup_err:
                    log.warning(f"    [WARN] Batch cleanup failed for {bname_}: {cleanup_err}")

            for bname in batch_names:
                # Retry upload with driver recovery on network failures
                MAX_UPLOAD_RETRIES = 3
                job_id = None
                for upload_attempt in range(1, MAX_UPLOAD_RETRIES + 1):
                    try:
                        job_id = uploader.upload_batch(driver, bname)
                        break  # success or graceful failure — either way, move on
                    except Exception as upload_err:
                        log.warning(
                            f"  [NETWORK] Upload attempt {upload_attempt}/{MAX_UPLOAD_RETRIES} "
                            f"crashed for {bname}: {upload_err}"
                        )
                        # Driver is likely dead — rebuild it
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = None
                        if upload_attempt < MAX_UPLOAD_RETRIES:
                            wait = 15 * (2 ** (upload_attempt - 1))  # 15s, 30s
                            log.info(f"  [NETWORK] Waiting {wait}s then rebuilding driver...")
                            time.sleep(wait)
                            if not _ensure_driver():
                                log.error("  [NETWORK] Driver recovery failed — giving up on this flush")
                                break

                batch_job_map[bname] = job_id

                # Find which videos belong to this batch via state
                state = sm.get_all()
                batch_pids = [pid for pid, rec in state.items()
                              if isinstance(rec, dict) and rec.get("batch") == bname]

                if job_id:
                    log.info(f"  [OK] {bname} -> job_id={job_id}")
                    # Update state.json synchronously (fast)
                    for pid in batch_pids:
                        sm.mark_uploaded(pid, job_id, today)
                    # Notion updates + cleanup in background thread
                    # NOT daemon — must complete before pipeline exits
                    t = threading.Thread(
                        target=_post_upload_work,
                        args=(bname, job_id, batch_pids),
                        name=f"post-{bname}",
                        daemon=False,
                    )
                    t.start()
                    post_upload_threads.append(t)
                else:
                    log.error(f"  [FAIL] {bname} upload returned no job_id")
                    for state_key in batch_pids:
                        sm.mark_failed(state_key, "upload_no_job_id")
                        rec = sm.get(state_key)
                        real_pid = rec.get("page_id", state_key) if rec else state_key
                        try:
                            nc.mark_failed_in_notion(real_pid)
                        except Exception as notion_err:
                            log.warning(f"    [WARN] Notion fail-mark error for {real_pid}: {notion_err}")

            # Wait for all background Notion updates to finish before next flush
            for t in post_upload_threads:
                t.join()

        # Track which page_ids have pending siblings (so we don't split them)
        # Build a lookup: page_id -> expected variant count from all_videos
        page_variant_count: dict[str, int] = {}
        for v in all_videos:
            pid = v["page_id"]
            page_variant_count[pid] = page_variant_count.get(pid, 0) + 1

        # Main consume loop
        while True:
            item = batch_q.get()
            if item is DONE:
                flush(pending)
                break

            v    = item
            lf   = v.get("local_file", "")
            size = os.path.getsize(lf) if lf and os.path.isfile(lf) else 0

            # Check if flushing now would split a page's language variants
            def _has_incomplete_page_group() -> bool:
                """True if any page_id in pending still has a sibling not yet arrived."""
                pending_pids: dict[str, int] = {}
                for pv in pending:
                    pid = pv["page_id"]
                    pending_pids[pid] = pending_pids.get(pid, 0) + 1
                for pid, count in pending_pids.items():
                    if count < page_variant_count.get(pid, 1):
                        return True
                return False

            # Flush when adding this video would exceed the batch limit,
            # BUT only if all page groups in pending are complete
            if pending and (pending_size + size) > MAX_BATCH_BYTES:
                if not _has_incomplete_page_group():
                    flush(pending)
                    pending      = []
                    pending_size = 0
                # else: keep accumulating — a sibling is still coming

            pending.append(v)
            pending_size += size

        if driver:
            try:
                driver.quit()
            except Exception:
                pass

        # ── Synchronous retry for any Notion updates that failed in background ──
        # The upload already happened on the admin site. We need Notion updated
        # so another PC won't re-upload. Retry for up to 10 minutes with backoff.
        # If still failing, save unsynced IDs so the NEXT run retries them first.
        if _notion_retry_queue:
            log.info(f"\n{'='*60}")
            log.info(f"  {len(_notion_retry_queue)} Notion update(s) failed in background.")
            log.info(f"  Retrying for up to 10 minutes...")
            log.info(f"{'='*60}")
            remaining = list(_notion_retry_queue)
            attempt = 0
            MAX_RETRY_SECONDS = 600  # 10 minutes
            start_time = time.time()
            while remaining and (time.time() - start_time) < MAX_RETRY_SECONDS:
                attempt += 1
                still_failed = []
                for pid in remaining:
                    try:
                        ok = nc.mark_uploaded_in_notion(pid, today)
                        if ok:
                            log.info(f"    [OK] Notion confirmed for {pid}")
                        else:
                            still_failed.append(pid)
                    except Exception as e:
                        log.warning(f"    [FAIL] {pid}: {e}")
                        still_failed.append(pid)
                remaining = still_failed
                if remaining:
                    elapsed = int(time.time() - start_time)
                    wait = min(30 * (2 ** (attempt - 1)), 120)  # 30s, 60s, cap 120s
                    log.info(
                        f"    {len(remaining)} pending | {elapsed}s/{MAX_RETRY_SECONDS}s "
                        f"| next retry in {wait}s..."
                    )
                    time.sleep(wait)

            if remaining:
                # Save unsynced page IDs so the next run picks them up
                import json as _json
                unsynced_path = os.path.join(os.path.dirname(__file__), "notion_unsynced.json")
                try:
                    # Merge with any existing unsynced IDs
                    existing = []
                    if os.path.isfile(unsynced_path):
                        with open(unsynced_path, "r") as f:
                            existing = _json.load(f)
                    merged = list(set(existing + remaining))
                    with open(unsynced_path, "w") as f:
                        _json.dump(merged, f, indent=2)
                    log.error(
                        f"\n  ⚠️  {len(remaining)} page(s) could not be confirmed in Notion "
                        f"after 10 minutes.\n"
                        f"  Saved to notion_unsynced.json — will auto-retry on next pipeline run.\n"
                        f"  DO NOT run on another PC until next run on THIS PC resolves them."
                    )
                except Exception as save_err:
                    log.error(f"  Could not save unsynced IDs: {save_err}")
                    log.error(f"  Unsynced page IDs: {remaining}")
            else:
                log.info(f"  All Notion updates confirmed. Safe to run on any PC.")

    # ── Start B + C threads ───────────────────────────────────────────────────
    ct = threading.Thread(target=compress_worker,    name="compress",      daemon=True)
    bt = threading.Thread(target=batch_upload_worker, name="batch-upload",  daemon=True)
    ct.start()
    bt.start()

    # ── Heartbeat: prints live progress every 30s ─────────────────────────────
    _stop_hb = threading.Event()

    def _heartbeat():
        while not _stop_hb.wait(30):
            try:
                counts = sm.summary()
                up   = counts.get("uploaded",    0)
                dl   = counts.get("downloaded",  0)
                fail = counts.get("failed",       0)
                pend = counts.get("pending",      0) + counts.get("downloading", 0)
                now  = datetime.now().strftime("%H:%M:%S")
                log.info(
                    f"[{now}] >> Pipeline | pending={pend}  downloaded={dl}"
                    f"  uploaded={up}  failed={fail}"
                )
            except Exception:
                pass

    threading.Thread(target=_heartbeat, daemon=True, name="heartbeat").start()

    # ── Run A: 3 parallel download workers ────────────────────────────────────
    log.info(f"\n{'='*60}")
    log.info(f"  Parallel pipeline: 3 download threads + compress + upload")
    log.info(f"  Videos to process: {len(all_videos)}")
    log.info(f"{'='*60}")

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="dl") as pool:
        futures = {pool.submit(download_one, v): v for v in all_videos}
        completed = 0
        for f in as_completed(futures):
            completed += 1
            v = futures[f]
            try:
                f.result()
            except Exception as e:
                log.error(f"  Download exception for {v['video_name']}: {e}")
                sm.mark_failed(_state_key(v), f"exception: {e}")
            log.info(f"  [PROGRESS] Downloads: {completed}/{len(all_videos)}")

    log.info("  All downloads done — waiting for compress + upload to finish ...")
    compress_q.put(DONE)
    ct.join()
    bt.join()
    _stop_hb.set()

    return batch_job_map


# ════════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="BabyBillion Notion -> Download -> Compress -> Batch -> Upload Pipeline"
    )
    parser.add_argument("--dry-run",       action="store_true", help="Show what would be processed, don't act")
    parser.add_argument("--skip-upload",   action="store_true", help="Stop after zipping (no upload)")
    parser.add_argument("--headless",      action="store_true", help="Run Chrome headless")
    parser.add_argument("--batch-only",    action="store_true", help="Only batch+zip+upload already-downloaded files")
    parser.add_argument("--status",        action="store_true", help="Print state summary and exit")
    parser.add_argument("--auto-finalize", action="store_true", help="Auto-finalize in Notion (skip review step)")
    args = parser.parse_args()

    # ── Status mode ───────────────────────────────────────────────────────────
    if args.status:
        counts = sm.summary()
        total  = sum(counts.values())
        log.info(f"\nPipeline State ({total} videos):")
        for status, n in sorted(counts.items()):
            log.info(f"  {status:20s}: {n}")
        return

    log.info(f"\n{'='*60}")
    log.info(f"  BabyBillion Notion Upload Pipeline  (parallel mode)")
    log.info(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"  Log: {log_path}")
    log.info(f"{'='*60}")

    # ── Stage 1: Fetch from Notion ────────────────────────────────────────────
    if args.batch_only:
        state_all  = sm.get_all()
        all_videos = []
        for pid, rec in state_all.items():
            if rec.get("pipeline_status") != "downloaded":
                continue
            vname      = rec.get("video_name", "")
            page_id    = rec.get("page_id", pid)
            lang_suffix = rec.get("lang_suffix", "")

            # Re-tag video name if not already tagged
            if vname and "___pg_" not in vname:
                short_pid = page_id.replace("-", "")
                if lang_suffix:
                    tagged = f"{vname}___pg_{short_pid}{lang_suffix}"
                else:
                    # Old single-link entries: no language suffix
                    tagged = f"{vname}___pg_{short_pid}"
                log.info(f"  [RETAG] {vname} → {tagged}")
                vname = tagged
                # Update state.json so future runs use the tagged name
                sm.upsert(pid, video_name=vname, lang_suffix=lang_suffix)

            all_videos.append({
                "page_id":     page_id,
                "video_name":  vname,
                "age_group":   rec.get("age_group", ""),
                "category":    rec.get("category", ""),
                "drive_link":  rec.get("drive_link", ""),
                "local_file":  rec.get("local_file", ""),
                "lang_suffix": lang_suffix,
            })
        log.info(f"Batch-only mode: {len(all_videos)} downloaded videos found.")
        # Sanity check even in batch-only mode (safety net)
        all_videos, batch_failed = sanity_checker.run(all_videos, mark_notion=True)
        if batch_failed:
            log.warning(
                f"  {len(batch_failed)} video(s) failed sanity check in batch-only mode "
                f"— marked 'Failed to upload' in Notion, will NOT be batched."
            )
        log.info(f"Batch-only mode: {len(all_videos)} videos passed sanity check.")
    else:
        all_videos = stage_fetch(dry_run=args.dry_run)

    if not all_videos:
        log.info("Nothing to do. Exiting.")
        return

    # ── Stages 2-6: Parallel download → compress → batch/zip/upload ──────────
    batch_job_map = run_parallel_pipeline(
        all_videos,
        headless=args.headless,
        skip_upload=args.skip_upload,
        auto_finalize=args.auto_finalize,
    )

    # ── Final summary ─────────────────────────────────────────────────────────
    log.info("\n" + "="*60)
    log.info("PIPELINE COMPLETE")
    log.info("="*60)
    counts = sm.summary()
    for status, n in sorted(counts.items()):
        log.info(f"  {status:20s}: {n}")
    log.info(f"\nLog saved to: {log_path}")


if __name__ == "__main__":
    main()

