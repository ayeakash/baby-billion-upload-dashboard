"""
batcher.py -- Groups downloaded MP4s into sub-70MB batches
and writes an admin-format CSV for each batch.

CSV field sanitization:
  - video_name : taken from the MP4 filename stem (already sanitized by
                 downloader.py), but re-checked here as a safety net
  - categories : whitespace-collapsed and stripped
                 (e.g. "Sight  words" -> "Sight words", " Colors " -> "Colors")

Output structure (inside BATCHES_DIR):
    Batch_01/        <- MP4 files (copied, originals stay in downloads/)
    Batch_01.csv     <- admin bulk-upload CSV
    Batch_02/
    Batch_02.csv
    ...
"""

import os
import re
import csv
import shutil
import logging
from config import (
    DOWNLOADS_DIR, BATCHES_DIR, MAX_BATCH_BYTES,
    ADMIN_CSV_HEADER, ADMIN_CHANNEL_NAME, ADMIN_CONTENT_TYPE, AGE_GROUP_MAP,
)
import state_manager as sm
from category_mapper import get_category_fields, is_valid_category, _normalize_age
from dedup_utils import normalize_video_key, build_uploaded_keys_from_state

log = logging.getLogger(__name__)


def _state_key(v: dict) -> str:
    """Composite state key: page_id + lang_suffix."""
    return v["page_id"] + v.get("lang_suffix", "")


def _sanitize_video_name(stem: str) -> str:
    """
    Ensure the video_name written to the admin CSV is clean:
      - Collapse consecutive underscores / spaces into one underscore
      - BUT preserve ___pg_ and ___ln_ tag separators (triple underscores)
      - Strip leading/trailing underscores or spaces
      - Remove characters the admin site might reject
    The stem is already sanitized by downloader.sanitize_filename, but this
    acts as a second pass in case the file was placed manually.
    """
    # Protect ___pg_ and ___ln_ markers from being collapsed
    name = stem.replace("___pg_", "\x00PG\x00").replace("___ln_", "\x00LN\x00")
    name = re.sub(r"[^\w\-\x00]", "_", name)   # replace anything non-word with _
    name = re.sub(r"_+", "_", name)              # collapse consecutive _
    # Restore the protected markers
    name = name.replace("\x00PG\x00", "___pg_").replace("\x00LN\x00", "___ln_")
    name = name.strip("_").strip()
    return name or "untitled"


def _sanitize_category(cat: str) -> str:
    """
    Clean a category string coming from Notion:
      - Collapse multiple spaces/tabs to a single space (e.g. "Sight  words")
      - Strip surrounding whitespace
      - Title-case it for consistency ("good habits" -> "Good Habits")
    """
    cat = re.sub(r"[ \t]+", " ", cat)   # collapse whitespace
    cat = cat.strip()
    return cat.title() if cat else "Education"



## _existing_batch_count removed -- batch numbering now uses
## state_manager.next_batch_number() for a persistent, monotonic counter.


def run(videos: list[dict]) -> list[str]:
    """
    Given a list of video dicts (each with page_id, video_name, age_group,
    category, local_file), group them into batches and write CSVs.

    videos: output from pipeline after download phase -- only those with
            local_file set and pipeline_status == 'downloaded'.

    Returns: list of batch names created (e.g. ["Batch_01", "Batch_02"])
    """
    os.makedirs(BATCHES_DIR, exist_ok=True)

    # ── Only process videos not yet batched ───────────────────────────────────
    to_batch = []
    for v in videos:
        rec = sm.get(_state_key(v))
        if rec and rec.get("pipeline_status") in ("batched", "zipped", "uploading", "uploaded"):
            log.info(f"  [SKIP] Already batched: {v['video_name']}")
            continue
        local_file = v.get("local_file") or (rec or {}).get("local_file")
        if not local_file or not os.path.isfile(local_file):
            log.warning(f"  [WARN] No local file for: {v['video_name']} -- skipping")
            continue
        v["local_file"] = local_file
        to_batch.append(v)

    if not to_batch:
        log.info("No new videos to batch.")
        return []

    # ── Validate categories against the mapping CSV ──────────────────────────
    valid_videos = []
    bad_category_videos = []
    for v in to_batch:
        age = _normalize_age(v.get("age_group", ""))
        notion_cat = v.get("category", "").strip()
        # Handle comma-separated categories (e.g. "Action words, Words")
        # Validate each part individually -- all must be valid
        if notion_cat and "," in notion_cat:
            parts = [p.strip() for p in notion_cat.split(",") if p.strip()]
            if all(is_valid_category(age, p) for p in parts):
                valid_videos.append(v)
            else:
                bad_category_videos.append(v)
        elif not notion_cat or not is_valid_category(age, notion_cat):
            bad_category_videos.append(v)
        else:
            valid_videos.append(v)

    if bad_category_videos:
        log.warning(f"\n  [== {len(bad_category_videos)} video(s) have UNRECOGNISED categories ==")
        log.warning(f"  |  These will NOT be batched. Marked 'Failed to upload' in Notion.")
        log.warning(f"  [{'='*60}")
        for v in bad_category_videos:
            age = _normalize_age(v.get("age_group", ""))
            log.warning(f"    [X] [{age}] '{v.get('category','')}' -- {v['video_name']}")
            sm.mark_failed(_state_key(v), "sanity:bad_category")
            # Also mark in Notion so it shows up as "Failed to upload"
            try:
                import notion_client as nc
                nc.mark_failed_in_notion(v["page_id"])  # real page_id for Notion API
            except Exception as e:
                log.warning(f"      Notion fail-mark error: {e}")
        log.warning("")

    to_batch = valid_videos
    if not to_batch:
        log.info("No videos with valid categories to batch.")
        return []

    # ── Guard: deduplicate by output filename ─────────────────────────────────
    #    Two videos with the same local filename would collide in the batch
    #    folder and CSV.  Keep only the first; log the rest as warnings.
    seen_fnames: dict[str, dict] = {}
    deduped = []
    for v in to_batch:
        fname = os.path.basename(v.get("local_file", "")).lower()
        if fname in seen_fnames:
            first = seen_fnames[fname]
            log.warning(
                f"  [DUPE] Skipping '{v['video_name']}' -- output file '{fname}' "
                f"already claimed by '{first['video_name']}' (page={first['page_id'][:12]}…)"
            )
            sm.set_status(_state_key(v), "skipped_duplicate")
            continue
        seen_fnames[fname] = v
        deduped.append(v)

    if len(deduped) < len(to_batch):
        log.warning(
            f"  Removed {len(to_batch) - len(deduped)} duplicate filename(s) "
            f"from batch input."
        )
    to_batch = deduped

    if not to_batch:
        log.info("No videos left after deduplication.")
        return []

    # ── Guard: reject content already uploaded (name+age match) ─────────────
    #    Safety net: even if a video slipped through fetch (e.g. --batch-only),
    #    refuse to batch content that already exists on the admin.
    #    Uses unified normalize_video_key() for consistent matching.
    state_all = sm.get_all()
    uploaded_keys = build_uploaded_keys_from_state(state_all)

    safe = []
    for v in to_batch:
        key = normalize_video_key(v.get("video_name", ""), v.get("age_group", ""))
        if key in uploaded_keys:
            log.warning(
                f"  [DUPE-UPLOAD] Skipping '{v['video_name']}' "
                f"(age={v.get('age_group','?')}) -- already uploaded in a prior run"
            )
            sm.set_status(_state_key(v), "skipped_duplicate")
            continue
        safe.append(v)
    if len(safe) < len(to_batch):
        log.warning(
            f"  Removed {len(to_batch) - len(safe)} already-uploaded video(s) "
            f"from batch input."
        )
    to_batch = safe

    if not to_batch:
        log.info("No videos left after upload-history check.")
        return []

    log.info(f"Batching {len(to_batch)} videos …")

    # ── Group by page_id so language variants stay together ────────────────
    #    Hindi + English of the same Notion page MUST be in the same batch.
    page_groups: dict[str, list[dict]] = {}
    for v in to_batch:
        pid = v["page_id"]
        page_groups.setdefault(pid, []).append(v)

    # Sort groups by first video name for deterministic ordering
    sorted_groups = sorted(page_groups.values(), key=lambda g: g[0]["video_name"])

    # ── Greedy bin-packing (page groups are atomic) ───────────────────────
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_size = 0

    for group in sorted_groups:
        group_size = sum(os.path.getsize(v["local_file"]) for v in group)
        # If adding this page group would exceed the limit, flush current batch
        if current_batch and (current_size + group_size) > MAX_BATCH_BYTES:
            batches.append(current_batch)
            current_batch = []
            current_size  = 0
        current_batch.extend(group)
        current_size += group_size

    if current_batch:
        batches.append(current_batch)

    # ── Reserve unique batch numbers via persistent counter ─────────────────
    start_n = sm.next_batch_number(count=len(batches))

    created = []
    for i, batch in enumerate(batches):
        batch_num    = start_n + i
        batch_name   = f"Batch_{batch_num:02d}"
        batch_folder = os.path.join(BATCHES_DIR, batch_name)
        batch_csv    = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
        os.makedirs(batch_folder, exist_ok=True)

        csv_rows = []
        for v in batch:
            fname = os.path.basename(v["local_file"])
            dst   = os.path.join(batch_folder, fname)
            if not os.path.isfile(dst):
                shutil.copy2(v["local_file"], dst)

            stem         = os.path.splitext(fname)[0]
            video_name   = _sanitize_video_name(stem)
            age          = _normalize_age(v.get("age_group", ""))
            notion_cat   = v.get("category", "")

            # Resolve comma-separated multi-categories individually
            if "," in notion_cat:
                parts = [p.strip() for p in notion_cat.split(",") if p.strip()]
                parents, cats = [], []
                for p in parts:
                    par, cat = get_category_fields(age, p)
                    if par and par not in parents:
                        parents.append(par)
                    cats.append(cat)
                parent_cat = ", ".join(parents)
                exact_cat  = ", ".join(cats)
            else:
                parent_cat, exact_cat = get_category_fields(age, notion_cat)

            if stem != video_name:
                log.info(f"    video_name sanitized: '{stem}' -> '{video_name}'")
            log.info(
                f"    category: '{notion_cat}' ({age}) "
                f"-> parent='{parent_cat}', cat='{exact_cat}'"
            )

            csv_rows.append({
                "video_name":        video_name,
                "categories_name":   parent_cat,
                "age_groups":        age,
                "channel_name":      ADMIN_CHANNEL_NAME,
                "tags":              "",
                "playlist_name":     exact_cat,
                "content_formats":   "",
                "content_types":     ADMIN_CONTENT_TYPE,
            })

            sm.mark_batched(_state_key(v), batch_name)

        with open(batch_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ADMIN_CSV_HEADER)
            writer.writeheader()
            writer.writerows(csv_rows)

        size_mb = sum(os.path.getsize(os.path.join(batch_folder, f))
                      for f in os.listdir(batch_folder)
                      if f.endswith(".mp4")) / 1024 / 1024
        log.info(f"  {batch_name}: {len(batch)} videos, {size_mb:.1f} MB -> {batch_csv}")
        created.append(batch_name)

    return created
