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
      - Strip ___pg_<hex> and ___ln_Hi/En pipeline tags
      - Collapse consecutive underscores / spaces into one underscore
      - Strip leading/trailing underscores or spaces
      - Remove characters the admin site might reject
    """
    # Strip ___pg_<hex> tag (12 or 32 hex chars)
    name = re.sub(r"___pg_[0-9a-f]+", "", stem)
    # Strip ___ln_Hi / ___ln_En language tag
    name = re.sub(r"___ln_(Hi|En|H|E)", "", name)
    # Clean up: replace non-word chars with _, collapse multiple _
    name = re.sub(r"[^\w\-]", "_", name)
    name = re.sub(r"_+", "_", name)
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

    # ── Guard: cross-check against batches.json (dashboard batches) ────────
    #    Even if state.json was reset or is stale, never re-batch a video
    #    that already exists in a dashboard batch.
    _batches_json = os.path.join(os.path.dirname(os.path.dirname(__file__)), "batches.json")
    if os.path.isfile(_batches_json):
        try:
            import json as _json
            with open(_batches_json, "r", encoding="utf-8") as _f:
                _bj = _json.load(_f)
            _existing_pids = set()
            for _bd in _bj.values():
                if isinstance(_bd, dict):
                    for _bv in _bd.get("videos", []):
                        pid = _bv.get("page_id", "")
                        if pid:
                            _existing_pids.add(pid)
            pre = len(to_batch)
            to_batch = [v for v in to_batch if v["page_id"] not in _existing_pids]
            skipped_bj = pre - len(to_batch)
            if skipped_bj:
                log.info(f"  [SKIP] {skipped_bj} video(s) already in a dashboard batch -- skipping.")
        except Exception as _e:
            log.warning(f"  [WARN] Could not read batches.json for cross-check: {_e}")

    if not to_batch:
        log.info("No new videos to batch.")
        return []

    # ── Log unrecognised categories (they still get batched) ───────────────────
    for v in to_batch:
        age = _normalize_age(v.get("age_group", ""))
        notion_cat = v.get("category", "").strip()
        if notion_cat and "," in notion_cat:
            parts = [p.strip() for p in notion_cat.split(",") if p.strip()]
            unrecognised = [p for p in parts if not is_valid_category(age, p)]
            if unrecognised:
                log.warning(f"  [WARN] [{age}] Unrecognised category parts {unrecognised} for {v['video_name']} -- batching with raw value")
        elif notion_cat and not is_valid_category(age, notion_cat):
            log.warning(f"  [WARN] [{age}] Unrecognised category '{notion_cat}' for {v['video_name']} -- batching with raw value")

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
    max_mb = MAX_BATCH_BYTES / (1024 * 1024)

    for group in sorted_groups:
        group_size = sum(os.path.getsize(v["local_file"]) for v in group)
        group_mb   = group_size / (1024 * 1024)

        # Warn if a single page group already exceeds the limit
        if group_size > MAX_BATCH_BYTES:
            names = [v['video_name'] for v in group]
            log.warning(
                f"  [WARN] Page group {group[0]['page_id'][:12]}… ({group_mb:.1f} MB, "
                f"{len(group)} variant(s): {names}) exceeds batch limit ({max_mb:.0f} MB). "
                f"It will be placed in its own batch."
            )

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
            orig_fname = os.path.basename(v["local_file"])
            orig_ext   = os.path.splitext(orig_fname)[1]   # .mp4
            orig_stem  = os.path.splitext(orig_fname)[0]

            # Clean video name: strip ___pg_ and ___ln_ tags
            video_name = _sanitize_video_name(orig_stem)

            # Derive language from lang_suffix
            lang_suffix = v.get("lang_suffix", "")
            if lang_suffix == "___ln_Hi":
                language = "Hindi"
            elif lang_suffix == "___ln_En":
                language = "English"
            else:
                language = ""

            # Add short _Hi/_En suffix only if both variants exist in this batch
            page_id = v["page_id"]
            siblings = [bv for bv in batch if bv["page_id"] == page_id]
            if len(siblings) > 1 and language:
                video_name = f"{video_name}_{language[:2]}"  # _Hi or _En

            # Copy file with clean name
            clean_fname = f"{video_name}{orig_ext}"
            dst = os.path.join(batch_folder, clean_fname)
            if not os.path.isfile(dst):
                shutil.copy2(v["local_file"], dst)

            age        = _normalize_age(v.get("age_group", ""))
            notion_cat = v.get("category", "")

            # Resolve comma-separated multi-categories individually
            if "," in notion_cat:
                parts = [p.strip() for p in notion_cat.split(",") if p.strip()]
                parents, cats = [], []
                for p in parts:
                    par, cat = get_category_fields(age, p)
                    if par and par not in parents:
                        parents.append(par)
                    cats.append((par, cat))
                # Filter out parent-only entries (where cat == parent, e.g., "Animals" -> ("Animals","Animals"))
                # These are just the parent category repeated — the real playlist is the child
                child_cats = [cat for par, cat in cats if cat != par]
                if not child_cats:
                    # All entries are parents — keep them all
                    child_cats = [cat for par, cat in cats]
                parent_cat = ", ".join(parents)
                exact_cat  = ", ".join(child_cats)
            else:
                parent_cat, exact_cat = get_category_fields(age, notion_cat)

            if orig_stem != video_name:
                log.info(f"    video_name: '{orig_stem}' -> '{video_name}'")
            log.info(
                f"    category: '{notion_cat}' ({age}) "
                f"-> parent='{parent_cat}', cat='{exact_cat}'"
            )

            csv_rows.append({
                "video_name":        video_name,
                "categories_name":   exact_cat,
                "age_groups":        age,
                "channel_name":      ADMIN_CHANNEL_NAME,
                "tags":              "",
                "playlist_name":     parent_cat,
                "content_formats":   "",
                "content_types":     ADMIN_CONTENT_TYPE,
                "language":          language,
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
