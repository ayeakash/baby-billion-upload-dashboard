"""
category_downloader.py — Download and batch videos by category mapping.

Instead of matching app CSV titles to Notion CSV titles, this script:
  1. Takes playlist IDs as input
  2. Uses the _AGE_ALIASES reverse map to find which Notion categories
     correspond to each playlist
  3. Pulls ALL videos from those Notion categories
  4. Downloads both Hindi and English variants from Drive
  5. Batches them using the pipeline's batcher (with proper ___pg_ / ___ln_ tagging)

Usage:
    python category_downloader.py <playlist_id_1> [playlist_id_2 ...]

    Options:
        --dry-run       List videos that would be downloaded without downloading
        --batch-only    Skip downloads, just batch already-downloaded MP4s
        --limit N       Download at most N videos (for testing)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import logging
import unicodedata
from collections import defaultdict
from datetime import datetime

# ── Resolve project paths ────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PIPELINE_DIR = os.path.join(PROJECT_ROOT, "pipeline")

if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import state_manager as sm
from downloader import download_video, sanitize_filename
from category_mapper import get_category_fields, _normalize_age

# Force UTF-8 on stdout/stderr for Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ── Constants ─────────────────────────────────────────────────────────────────
NOTION_CSV   = os.path.join(SCRIPT_DIR, "notion.csv")
PLAYLIST_CSV = os.path.join(SCRIPT_DIR,
    "Copy of Playlists Language Tagging - Playlist_new (1).csv")
LANGUAGE_MARKING_CSV = os.path.join(SCRIPT_DIR,
    "English_Hindi Videos Marking - All Videos.csv")

DOWNLOADS_DIR = os.path.join(SCRIPT_DIR, "downloads")
BATCHES_DIR   = os.path.join(PROJECT_ROOT, "batches")
BATCHES_JSON  = os.path.join(PROJECT_ROOT, "batches.json")

MAX_BATCH_BYTES = 30 * 1024 * 1024   # 30 MB

ADMIN_CSV_HEADER = [
    "video_name", "categories_name", "age_groups",
    "channel_name", "tags", "playlist_name",
    "content_formats", "content_types", "language",
]
ADMIN_CHANNEL_NAME = "BabyBillion_Education"
ADMIN_CONTENT_TYPE = "Original"

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(os.path.join(SCRIPT_DIR, "logs"), exist_ok=True)
log_path = os.path.join(SCRIPT_DIR, "logs",
    f"category_dl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("category_downloader")


# ═══════════════════════════════════════════════════════════════════════════════
# REVERSE ALIAS MAP: playlist_name → set of Notion categories
# ═══════════════════════════════════════════════════════════════════════════════

# Copied from category_mapper.py _AGE_ALIASES — this is the source of truth
_AGE_ALIASES = {
    ("6+", "nature"):             "explore nature around",
    ("6+", "seasons"):            "why seasons change",
    ("6+", "about india"):        "know your india",
    ("6+", "countries/geography"):"visit new countries",
    ("6+", "countries"):          "visit new countries",
    ("6+", "science"):            "discover science secrets",
    ("6+", "space"):              "explore outer space",
    ("6+", "technology"):         "how gadgets work",
    ("6+", "my body"):            "know your body",
    ("6+", "animals"):            "meet amazing animals",
    ("6+", "plants"):             "watch plants grow",
    ("6+", "food"):               "choose healthy foods",
    ("6+", "good habits"):        "build good habits",
    ("6+", "emotions"):           "understand your feelings",
    ("6+", "safety"):             "stay safe everyday",
    ("6+", "community helpers"):  "meet everyday helpers",
    ("6+", "sports"):             "explore different sports",
    ("6+", "knowledge"):          "amazing facts inside",
    ("3-6", "fruits"):            "name tasty fruits",
    ("3-6", "vegetables"):        "know your vegetables",
    ("3-6", "food items"):        "what's on plate",
    ("3-6", "food"):              "what's on plate",
    ("3-6", "plants"):            "watch plants grow",
    ("3-6", "nature"):            "explore nature around",
    ("3-6", "space"):             "visit outer space",
    ("3-6", "science"):           "science made fun",
    ("3-6", "good habits"):       "build good habits",
    ("3-6", "emotions"):          "what's that feeling",
    ("3-6", "safety"):            "stay safe everyday",
    ("3-6", "community helpers"): "meet helpful people",
    ("3-6", "vehicles"):          "spot cool vehicles",
    ("3-6", "colors"):            "learn color names",
    ("3-6", "my body"):           "know your body",
    ("3-6", "toys"):              "discover fun toys",
    ("3-6", "abc"):               "know your alphabets",
    ("3-6", "cvc"):               "read simple words",
    ("3-6", "cvc words"):         "read simple words",
    ("3-6", "phonics"):           "sounds & words",
    ("3-6", "sight words"):       "speak it right",
    ("3-6", "simple sentences"):  "start with sentences",
    ("3-6", "english speaking"):  "speak with confidence",
    ("3-6", "tracing abc"):       "write your alphabets",
    ("3-6", "123"):               "count with confidence",
    ("3-6", "number ordering"):   "place your numbers",
    ("3-6", "shapes"):            "learn your shapes",
    ("3-6", "tracing 123"):       "write your numbers",
    ("3-6", "patterns"):          "play with patterns",
    ("3-6", "addition"):          "add with fun",
    ("3-6", "subtraction"):       "subtract with fun",
    ("3-6", "farm animals"):      "farm animals",
    ("3-6", "wild animals"):      "jungle animals",
    ("3-6", "sea animals"):       "water animals",
    ("3-6", "baby animals"):      "baby animals",
    ("0-3", "abc"):               "learn your abc",
    ("0-3", "action words"):      "try these actions",
    ("0-3", "words"):             "learn new words",
    ("0-3", "rhymes"):            "sing along rhymes",
    ("0-3", "hindi poems"):       "listen to poems",
    ("0-3", "musical instruments"): "listen and enjoy",
    ("0-3", "music instruments"): "listen and enjoy",
    ("0-3", "123"):               "count with confidence",
    ("0-3", "hindi counting"):    "count in hindi",
    ("0-3", "shapes"):            "spot different shapes",
    ("0-3", "hindi basics"):      "speak simple hindi",
    ("0-3", "farm animals"):      "meet farm friends",
    ("0-3", "birds"):             "spot colorful birds",
    ("0-3", "sea animals"):       "meet ocean animals",
    ("0-3", "insects"):           "meet tiny insects",
    ("0-3", "fruits"):            "name your fruits",
    ("0-3", "vegetables"):        "name your veggies",
    ("0-3", "nature"):            "explore nature around",
    ("0-3", "plants"):            "watch plants grow",
    ("0-3", "animals"):           "meet cute animals",
    ("0-3", "colors"):            "learn color names",
    ("0-3", "toys"):              "find favorite toys",
    ("0-3", "vehicles"):          "spot moving vehicles",
    ("0-3", "my family"):         "meet your family",
    ("0-3", "my body"):           "know body parts",
    ("0-3", "good habits"):       "practice good habits",
    ("0-3", "emotions"):          "how are you",
    ("0-3", "home items"):        "find things around",
    ("0-3", "festivals"):         "celebrate with everyone",
    ("0-3", "clothes"):           "what's everyone wearing",
    ("0-3", "cloths"):            "what's everyone wearing",
    ("0-3", "opposites"):         "learn opposite words",
    ("0-3", "places we go"):      "let's go outside",
    ("0-3", "professions"):       "what do they do",
    ("3-6", "relationships"):     "my family",
    ("0-3", "relationships"):     "meet your family",
    ("3-6", "weather"):           "seasons",
    ("6+", "weather"):            "why seasons change",
    ("3-6", "physical movement"): "action words",
    ("0-3", "physical movement"): "try these actions",
}


def _normalize(s):
    return " ".join(s.strip().lower().split())


def build_reverse_map():
    """playlist_name_lower → set of notion_category_lower"""
    reverse = defaultdict(set)
    for (age, notion_cat_norm), playlist_name_norm in _AGE_ALIASES.items():
        reverse[playlist_name_norm].add(notion_cat_norm)
    return reverse


# ═══════════════════════════════════════════════════════════════════════════════
# LOAD DATA
# ═══════════════════════════════════════════════════════════════════════════════

def load_playlists():
    mapping = {}
    with open(PLAYLIST_CSV, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pid = row.get("playlist_id", "").strip().lower()
            if pid:
                mapping[pid] = {
                    "title": row.get("title", "").strip(),
                    "language": row.get("Language", "Both").strip(),
                    "age_groups": row.get("age_groups", "").strip(),
                }
    return mapping


def load_language_marking() -> dict:
    """
    Load the English/Hindi language marking CSV.
    Builds lookup: sanitized_title_lower -> "Hindi" | "English"
    This is the source of truth for which language a video is.
    """
    lookup = {}
    if not os.path.isfile(LANGUAGE_MARKING_CSV):
        log.warning(f"Language marking CSV not found: {LANGUAGE_MARKING_CSV}")
        return lookup
    with open(LANGUAGE_MARKING_CSV, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            title = (row.get("title") or "").strip()
            lang  = (row.get("Language") or "").strip()
            if title and lang:
                # Store by raw title (lowercase) for matching
                lookup[title.lower()] = lang.capitalize()  # "Hindi" or "English"
    log.info(f"Loaded {len(lookup)} language markings from marking CSV")
    return lookup


def resolve_language(video_name: str, lang_suffix: str, lang_lookup: dict) -> str:
    """
    Determine the language for a video.
    Priority:
      1. Language marking CSV (source of truth)
      2. Fall back to ___ln_ suffix from Notion Drive link
    Returns "Hindi" or "English".
    """
    # Try matching by video name in the marking CSV
    name_lower = video_name.lower()
    if name_lower in lang_lookup:
        return lang_lookup[name_lower]

    # Fall back to the Drive link language suffix
    if lang_suffix == "___ln_Hi":
        return "Hindi"
    elif lang_suffix == "___ln_En":
        return "English"
    return "Hindi"  # default


def _build_notion_page_id_lookup() -> dict:
    """
    Query the Notion API to build a lookup: video_name_lower → real page_id.
    Returns empty dict if Notion API is unavailable or credentials aren't set.
    """
    try:
        from config import NOTION_TOKEN, NOTION_DATABASE_ID
        if not NOTION_TOKEN or not NOTION_DATABASE_ID:
            log.warning("Notion credentials not configured — will use MD5-based page IDs")
            return {}

        import notion_client as nc
        if not nc.validate_connection():
            log.warning("Notion API connection failed — will use MD5-based page IDs")
            return {}

        # Query ALL pages (no status filter) to build a comprehensive lookup
        import requests
        BASE = "https://api.notion.com/v1"
        headers = {
            "Authorization":  f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type":   "application/json",
        }
        lookup = {}
        cursor = None
        total = 0

        while True:
            payload = {
                "database_id": NOTION_DATABASE_ID,
                "page_size": 100,
            }
            if cursor:
                payload["start_cursor"] = cursor

            resp = requests.post(
                f"{BASE}/databases/{NOTION_DATABASE_ID}/query",
                headers=headers, json=payload, timeout=30
            )
            if resp.status_code != 200:
                log.warning(f"Notion query failed ({resp.status_code}) — will use MD5-based page IDs")
                return {}

            data = resp.json()
            for page in data.get("results", []):
                page_id = page["id"]
                props = page.get("properties", {})
                # Extract video name from title property
                vn_prop = props.get("Video Name", {})
                vname = ""
                if vn_prop.get("type") == "title":
                    for t in vn_prop.get("title", []):
                        vname += t.get("plain_text", "")
                vname = vname.strip()
                if vname:
                    lookup[vname.lower()] = page_id
                    total += 1

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        log.info(f"Built Notion page ID lookup: {total} video names → real page IDs")
        return lookup

    except Exception as e:
        log.warning(f"Could not build Notion page ID lookup: {e} — will use MD5-based page IDs")
        return {}


def load_notion_by_categories(target_categories: set[str]) -> list[dict]:
    """
    Load all Notion CSV rows whose Category matches any of the target categories.
    For each row with both Hindi and English links, creates two entries (like pipeline.py).
    Uses real Notion page IDs when available, falls back to MD5 hashes.
    """
    # Try to get real Notion page IDs
    notion_lookup = _build_notion_page_id_lookup()
    using_real_ids = bool(notion_lookup)
    if not using_real_ids:
        log.warning("Using MD5-based page IDs (Notion API lookup unavailable)")

    videos = []
    seen_keys = set()
    real_id_count = 0
    md5_fallback_count = 0

    with open(NOTION_CSV, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            vname = (row.get("Video Name") or "").strip()
            cat   = (row.get("Category") or "").strip()
            if not vname:
                continue

            # Check if category matches (split compound categories)
            cat_parts = [_normalize(c) for c in cat.split(",")]
            if not any(cp in target_categories for cp in cat_parts):
                continue

            hindi_link   = (row.get("Final Video Hindi Link") or "").strip()
            english_link = (row.get("Final Video English Link") or "").strip()
            age_group    = (row.get("Age Group") or "").strip()
            status       = (row.get("Status") or "").strip()

            has_hindi   = "drive.google.com" in hindi_link
            has_english = "drive.google.com" in english_link

            if not has_hindi and not has_english:
                continue

            # Resolve real Notion page ID, fall back to MD5 hash
            real_pid = notion_lookup.get(vname.lower())
            if real_pid:
                page_id = real_pid
                # Real Notion IDs: strip dashes for the ___pg_ tag (same as pipeline)
                short_pid = page_id.replace("-", "")
                real_id_count += 1
            else:
                page_id = hashlib.md5(vname.encode()).hexdigest()
                short_pid = page_id[:12]
                md5_fallback_count += 1

            # Create language variants (same as pipeline.py)
            link_variants = []
            if has_hindi:
                link_variants.append((hindi_link, "___ln_Hi"))
            if has_english:
                link_variants.append((english_link, "___ln_En"))

            for drive_link, lang_suffix in link_variants:
                safe_name = sanitize_filename(vname)
                tagged_name = f"{safe_name}___pg_{short_pid}{lang_suffix}"

                # Deduplicate
                dedup_key = tagged_name.lower()
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                videos.append({
                    "page_id":     page_id,
                    "video_name":  tagged_name,
                    "original_name": vname,
                    "age_group":   age_group,
                    "category":    cat,
                    "drive_link":  drive_link,
                    "lang_suffix": lang_suffix,
                    "status":      status,
                    "language":    "",  # resolved later via marking CSV
                })

    if using_real_ids:
        log.info(f"Page IDs: {real_id_count} real Notion IDs, {md5_fallback_count} MD5 fallbacks")
    return videos


# ═══════════════════════════════════════════════════════════════════════════════
# DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════════════

def download_all_videos(videos: list[dict], limit: int | None = None) -> list[dict]:
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    if limit:
        videos = videos[:limit]
        log.info(f"  Limiting to first {limit} video entries")

    total = len(videos)
    downloaded = []
    failed = 0

    for i, v in enumerate(videos, 1):
        name       = v["video_name"]
        drive_link = v["drive_link"]
        log.info(f"  [{i}/{total}] {name}")

        # Check if already downloaded
        expected = os.path.join(DOWNLOADS_DIR, f"{name}.mp4")
        if os.path.isfile(expected) and os.path.getsize(expected) > 10_000:
            log.info(f"    Already exists: {expected}")
            v["local_file"] = expected
            downloaded.append(v)
            continue

        local_file = download_video(v["page_id"], name, drive_link)
        if local_file and os.path.isfile(local_file):
            our_path = os.path.join(DOWNLOADS_DIR, os.path.basename(local_file))
            if os.path.abspath(local_file) != os.path.abspath(our_path):
                shutil.move(local_file, our_path)
                local_file = our_path
            v["local_file"] = local_file
            downloaded.append(v)
        else:
            failed += 1
            log.warning(f"    FAILED to download: {name}")

    log.info(f"\nDownload complete: {len(downloaded)} succeeded, {failed} failed out of {total}")
    return downloaded


# ═══════════════════════════════════════════════════════════════════════════════
# BATCHING (uses pipeline's batcher.py logic with category_mapper)
# ═══════════════════════════════════════════════════════════════════════════════

def _sanitize_video_name(stem: str) -> str:
    """Same as batcher.py's _sanitize_video_name — preserves ___pg_ and ___ln_ tags."""
    name = stem.replace("___pg_", "\x00PG\x00").replace("___ln_", "\x00LN\x00")
    name = re.sub(r"[^\w\-\x00]", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.replace("\x00PG\x00", "___pg_").replace("\x00LN\x00", "___ln_")
    name = name.strip("_").strip()
    return name or "untitled"


def _load_batches_json() -> dict:
    if os.path.isfile(BATCHES_JSON):
        try:
            with open(BATCHES_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Error reading batches.json: {e}")
    return {}


def _save_batches_json(batches: dict):
    tmp_file = BATCHES_JSON + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(batches, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, BATCHES_JSON)
    except Exception as e:
        log.error(f"Error saving batches.json: {e}")
        if os.path.isfile(tmp_file):
            try: os.remove(tmp_file)
            except: pass


def create_batches(videos: list[dict]) -> list[str]:
    if not videos:
        log.info("No videos to batch.")
        return []

    os.makedirs(BATCHES_DIR, exist_ok=True)

    # Filter to downloadable videos
    to_batch = []
    for v in videos:
        local = v.get("local_file", "")
        if local and os.path.isfile(local) and os.path.getsize(local) > 10_000:
            state_key = v["page_id"] + v.get("lang_suffix", "")
            rec = sm.get(state_key)
            if rec and rec.get("pipeline_status") in ("batched", "zipped", "uploading", "uploaded"):
                log.info(f"  [SKIP] Already batched: {v['video_name']}")
                continue
            to_batch.append(v)
        else:
            log.warning(f"  [WARN] No local file for: {v['video_name']}")

    if not to_batch:
        log.info("No new videos to batch.")
        return []

    # Deduplicate by filename
    seen = {}
    deduped = []
    for v in to_batch:
        fname = os.path.basename(v["local_file"]).lower()
        if fname in seen:
            log.warning(f"  [DUPE] Skipping: {v['video_name']}")
            continue
        seen[fname] = v
        deduped.append(v)
    to_batch = deduped

    log.info(f"Batching {len(to_batch)} video files into <=30 MB batches ...")

    # Group by page_id so Hindi + English stay together
    page_groups: dict[str, list[dict]] = {}
    for v in to_batch:
        pid = v["page_id"]
        page_groups.setdefault(pid, []).append(v)

    sorted_groups = sorted(page_groups.values(), key=lambda g: g[0]["video_name"])

    # Greedy bin-packing
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_size = 0

    for group in sorted_groups:
        group_size = sum(os.path.getsize(v["local_file"]) for v in group)
        if current_batch and (current_size + group_size) > MAX_BATCH_BYTES:
            batches.append(current_batch)
            current_batch = []
            current_size = 0
        current_batch.extend(group)
        current_size += group_size

    if current_batch:
        batches.append(current_batch)

    start_n = sm.next_batch_number(count=len(batches))
    all_batches_data = _load_batches_json()
    created = []

    for i, batch in enumerate(batches):
        batch_num    = start_n + i
        batch_name   = f"Batch_{batch_num:02d}"
        batch_folder = os.path.join(BATCHES_DIR, batch_name)
        batch_csv    = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
        os.makedirs(batch_folder, exist_ok=True)

        csv_rows = []
        batch_videos_meta = []

        for v in batch:
            fname = os.path.basename(v["local_file"])
            dst   = os.path.join(batch_folder, fname)
            if not os.path.isfile(dst):
                shutil.copy2(v["local_file"], dst)

            stem       = os.path.splitext(fname)[0]
            video_name = _sanitize_video_name(stem)
            age        = _normalize_age(v.get("age_group", ""))
            notion_cat = v.get("category", "")

            # Resolve category using category_mapper (same as pipeline batcher)
            if "," in notion_cat:
                parts = [p.strip() for p in notion_cat.split(",") if p.strip()]
                parents, cats = [], []
                for p in parts:
                    par, cat = get_category_fields(age, p)
                    if par and par not in parents:
                        parents.append(par)
                    cats.append((par, cat))
                child_cats = [cat for par, cat in cats if cat != par]
                if not child_cats:
                    child_cats = [cat for par, cat in cats]
                parent_cat = ", ".join(parents)
                exact_cat  = ", ".join(child_cats)
            else:
                parent_cat, exact_cat = get_category_fields(age, notion_cat)

            # Derive language from lang_suffix
            lang_suffix = v.get("lang_suffix", "")
            if lang_suffix == "___ln_Hi":
                language = "Hindi"
            elif lang_suffix == "___ln_En":
                language = "English"
            else:
                language = v.get("language", "")

            # Strip language suffix from video_name (now in separate column)
            csv_video_name = re.sub(r"___ln_(Hi|En|H|E)$", "", video_name)

            log.info(f"    [{batch_name}] {csv_video_name} [{language}]")
            log.info(f"      category: '{notion_cat}' ({age}) -> parent='{parent_cat}', cat='{exact_cat}'")

            csv_rows.append({
                "video_name":      csv_video_name,
                "categories_name": exact_cat,
                "age_groups":      age,
                "channel_name":    ADMIN_CHANNEL_NAME,
                "tags":            "",
                "playlist_name":   parent_cat,
                "content_formats": "",
                "content_types":   ADMIN_CONTENT_TYPE,
                "language":        language,
            })

            state_key = v["page_id"] + v.get("lang_suffix", "")
            sm.upsert(
                state_key,
                page_id=v["page_id"],
                video_name=v["video_name"],
                age_group=age,
                category=notion_cat,
                local_file=v["local_file"],
                pipeline_status="batched",
                batch=batch_name,
                lang_suffix=v.get("lang_suffix", ""),
                source="category_downloader",
            )

            batch_videos_meta.append({
                "page_id":         v["page_id"],
                "video_name":      v["video_name"],
                "age_group":       age,
                "category":        notion_cat,
                "local_file":      v["local_file"],
                "drive_link":      v.get("drive_link", ""),
                "pipeline_status": "batched",
                "lang_suffix":     v.get("lang_suffix", ""),
            })

        with open(batch_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ADMIN_CSV_HEADER)
            writer.writeheader()
            writer.writerows(csv_rows)

        all_batches_data[batch_name] = {
            "batch_name":     batch_name,
            "status":         "pending_first_review",
            "created_at":     datetime.now().isoformat(),
            "videos":         batch_videos_meta,
            "upload_job_id":  None,
            "upload_date":    None,
            "finalized_date": None,
        }

        size_mb = sum(
            os.path.getsize(os.path.join(batch_folder, f))
            for f in os.listdir(batch_folder) if f.endswith(".mp4")
        ) / (1024 * 1024)
        log.info(f"  {batch_name}: {len(batch)} videos, {size_mb:.1f} MB -> {batch_csv}")
        created.append(batch_name)

    _save_batches_json(all_batches_data)
    log.info(f"\nCreated {len(created)} batch(es): {', '.join(created)}")
    return created


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Download & batch videos by category mapping (Notion CSV)."
    )
    parser.add_argument("playlist_ids", nargs="+",
        help="One or more playlist UUIDs to process")
    parser.add_argument("--dry-run", action="store_true",
        help="List videos without downloading")
    parser.add_argument("--batch-only", action="store_true",
        help="Skip downloads, batch already-downloaded files")
    parser.add_argument("--limit", type=int, default=None,
        help="Max number of videos to download")
    args = parser.parse_args()

    log.info("=" * 70)
    log.info("  Category-Based Downloader & Batcher")
    log.info("=" * 70)

    # ── 1. Load playlists & language marking ──────────────────────────────────
    pl_map = load_playlists()
    reverse_map = build_reverse_map()
    lang_lookup = load_language_marking()

    # ── 2. For each playlist, find target Notion categories ───────────────────
    all_categories = set()
    playlist_info = []

    for pid in args.playlist_ids:
        pid_lower = pid.strip().lower()
        pl = pl_map.get(pid_lower)
        if not pl:
            log.warning(f"  Playlist {pid} not found in playlist mapping CSV — skipping")
            continue

        title = pl["title"]
        title_key = _normalize(title)

        # Get mapped categories from reverse alias map
        cats = reverse_map.get(title_key, set())
        # Also add the title itself as a potential category
        cats.add(title_key)

        log.info(f"  Playlist: {title} ({pid_lower[:12]}...)")
        log.info(f"    -> Notion categories: {sorted(cats)}")

        all_categories.update(cats)
        playlist_info.append((pid_lower, title, cats))

    if not all_categories:
        log.warning("No categories resolved for any playlist. Exiting.")
        sys.exit(0)

    log.info(f"\n  Total target categories: {sorted(all_categories)}")

    # ── 3. Load Notion videos by category ─────────────────────────────────────
    videos = load_notion_by_categories(all_categories)

    if not videos:
        log.warning("No videos found in Notion CSV for these categories. Exiting.")
        sys.exit(0)

    # ── 4. Resolve language for each video using marking CSV ───────────────
    for v in videos:
        v["language"] = resolve_language(
            v["original_name"], v["lang_suffix"], lang_lookup
        )

    # Count stats
    unique_videos = len(set(v["original_name"] for v in videos))
    hindi_count = sum(1 for v in videos if v["language"] == "Hindi")
    english_count = sum(1 for v in videos if v["language"] == "English")

    log.info(f"\n  Found {unique_videos} unique videos ({len(videos)} total entries)")
    log.info(f"    Hindi variants:   {hindi_count}")
    log.info(f"    English variants: {english_count}")

    # ── 4. Dry run ────────────────────────────────────────────────────────────
    if args.dry_run:
        log.info("\n[DRY RUN] Videos that would be downloaded:\n")
        for i, v in enumerate(videos, 1):
            link_short = v["drive_link"][:60] + "..." if len(v["drive_link"]) > 60 else v["drive_link"]
            log.info(f"  {i:4d}. [{v['age_group']}] [{v['lang_suffix']}] {v['original_name']}")
            log.info(f"        Category: {v['category']}")
            log.info(f"        -> {link_short}")
        log.info(f"\nTotal: {len(videos)} video entries ({unique_videos} unique)")
        return

    # ── 5. Download ───────────────────────────────────────────────────────────
    if args.batch_only:
        log.info("\n[BATCH-ONLY] Collecting existing files ...")
        downloaded = []
        for v in videos:
            expected = os.path.join(DOWNLOADS_DIR, f"{v['video_name']}.mp4")
            if os.path.isfile(expected) and os.path.getsize(expected) > 10_000:
                v["local_file"] = expected
                downloaded.append(v)
        log.info(f"  Found {len(downloaded)} already-downloaded video files")
    else:
        log.info(f"\nStarting download of {len(videos)} video entries ...\n")
        downloaded = download_all_videos(videos, limit=args.limit)

    # ── 6. Batch ──────────────────────────────────────────────────────────────
    if downloaded:
        log.info(f"\nBatching {len(downloaded)} video files ...\n")
        created = create_batches(downloaded)
        if created:
            log.info(f"\n{'='*70}")
            log.info(f"  Done! Created {len(created)} batch(es).")
            log.info(f"  Batches are in: {BATCHES_DIR}")
            log.info(f"  Registered in batches.json and state.json")
            log.info(f"{'='*70}")
    else:
        log.warning("No videos were downloaded/found. Nothing to batch.")


if __name__ == "__main__":
    main()
