"""
notion_client.py -- Wrapper for the Notion API.

Responsibilities:
  - Query the database for videos that are EXACTLY "Ready to Upload" and NOT yet uploaded
  - Update page properties after successful upload (Upload=Yes, Upload Date=today)

Filter chain (triple-validated):
  Layer 1 -- Notion API filter:  Status = "Ready to Upload"  (server-side)
  Layer 2 -- Notion API filter:  Upload = "No" or unchecked  (server-side, type auto-detected)
  Layer 3 -- Python validation:  re-checks both fields + confirms Drive link exists

Notion API docs: https://developers.notion.com/reference
"""
from __future__ import annotations

import re
import unicodedata
import requests
import logging
from datetime import date
from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID,
    PROP_VIDEO_NAME, PROP_AGE_GROUP, PROP_CATEGORY,
    PROP_STATUS, PROP_UPLOAD, PROP_UPLOAD_DATE, PROP_UPLOAD_PROGRESS,
    PROP_FINAL_VIDEO_HINDI_LINK, PROP_FINAL_VIDEO_ENGLISH_LINK,
    PROP_FAILED_UPLOAD, PROP_REDO, PROP_REDO_REASON,
    PROP_HINDI_TITLE_ON_APP, PROP_ENGLISH_TITLE_ON_APP,
    PROP_BATCH_ID,
    STATUS_READY, STATUS_FAILED_UPLOAD, STATUS_UPLOADED,
    UPLOAD_NO, UPLOAD_YES,
    UPLOAD_PROGRESS_PROCESSING, UPLOAD_PROGRESS_DRAFT, UPLOAD_PROGRESS_REVIEWED,
    NOTION_READ_ONLY,
)

log = logging.getLogger(__name__)

NOTION_VERSION = "2025-09-03"
BASE = "https://api.notion.com/v1"


def _notion_write_blocked(fn_name: str) -> bool:
    """Return True (and log) if Notion is in read-only mode."""
    if NOTION_READ_ONLY:
        log.info(f"  [READ-ONLY] Skipped Notion write: {fn_name}()")
        return True
    return False

# Cached data source ID (resolved from database on first connect)
_data_source_id: str | None = None
_use_data_source_url: bool = True  # True = /data_sources/{id}/query, False = /databases/{id}/query

# Cached after first successful detection
_upload_prop_type: str | None = None   # "select" | "checkbox" | "rich_text"
_status_prop_type: str | None = None   # "select" | "status"


def _resolve_data_source_id() -> str:
    """
    Discover the data source ID from the database.
    With Notion API 2025-09-03, databases are containers for data sources.
    Queries must target /v1/data_sources/{id}/query instead of /v1/databases/{id}/query.
    Falls back to /v1/databases/{id}/query if no data sources exist.
    """
    global _data_source_id, _use_data_source_url
    if _data_source_id:
        return _data_source_id

    _check_config()
    url = f"{BASE}/databases/{NOTION_DATABASE_ID}"
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    db = resp.json()
    data_sources = db.get("data_sources", [])

    if not data_sources:
        # Fallback: database has no multi-source — query via /databases/ endpoint
        log.warning("No data_sources found — using /databases/ query endpoint as fallback")
        _data_source_id = NOTION_DATABASE_ID
        _use_data_source_url = False
        return _data_source_id

    # Pick the first data source that has content (non-empty query)
    for ds in data_sources:
        ds_id = ds.get("id")
        if ds_id:
            test_url = f"{BASE}/data_sources/{ds_id}/query"
            test_resp = requests.post(test_url, headers=_headers(), json={"page_size": 1}, timeout=15)
            if test_resp.status_code == 200 and test_resp.json().get("results"):
                _data_source_id = ds_id
                _use_data_source_url = True
                log.info(f"Resolved data source: {ds_id}")
                return _data_source_id

    # If no data source had results, just use the first one
    _data_source_id = data_sources[0].get("id", NOTION_DATABASE_ID)
    _use_data_source_url = True
    log.info(f"Using first data source: {_data_source_id}")
    return _data_source_id


def _query_url() -> str:
    """Return the correct query URL for the current Notion API."""
    ds_id = _resolve_data_source_id()
    if _use_data_source_url:
        return f"{BASE}/data_sources/{ds_id}/query"
    else:
        return f"{BASE}/databases/{ds_id}/query"


def _headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type":  "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _check_config():
    if not NOTION_TOKEN:
        raise ValueError(
            "NOTION_TOKEN is not set.\n"
            "Run:  $env:NOTION_TOKEN = 'secret_xxxx'\n"
            "or edit NOTION_TOKEN in config.py"
        )
    if not NOTION_DATABASE_ID:
        raise ValueError(
            "NOTION_DATABASE_ID is not set.\n"
            "Copy the 32-char ID from your Notion database URL and set\n"
            "NOTION_DATABASE_ID in config.py or as an env var."
        )


# ── Property extractors ────────────────────────────────────────────────────────

def _extract_title(prop) -> str:
    """Extract plain text from a title property."""
    parts = prop.get("title", [])
    return "".join(p.get("plain_text", "") for p in parts).strip()


def _extract_rich_text(prop) -> str:
    parts = prop.get("rich_text", [])
    return "".join(p.get("plain_text", "") for p in parts).strip()


def _extract_select(prop) -> str:
    sel = prop.get("select")
    return sel["name"] if sel else ""


def _extract_url(prop) -> str:
    return prop.get("url") or ""


def _extract_checkbox(prop) -> bool:
    return prop.get("checkbox", False)


def _prop_value(properties: dict, name: str) -> str:
    """Generic extractor -- handles title, rich_text, select, url, checkbox."""
    prop = properties.get(name)
    if prop is None:
        return ""
    t = prop.get("type", "")
    if t == "title":      return _extract_title(prop)
    if t == "rich_text":  return _extract_rich_text(prop)
    if t == "select":     return _extract_select(prop)
    if t == "status":
        # Notion 'status' type has same structure as 'select': {"name": "..."}
        s = prop.get("status")
        return s["name"] if s else ""
    if t == "url":        return _extract_url(prop)
    if t == "checkbox":   return "Yes" if _extract_checkbox(prop) else "No"
    if t == "date":
        d = prop.get("date")
        return d["start"] if d else ""
    # Multi-select -- join with comma
    if t == "multi_select":
        return ", ".join(o["name"] for o in prop.get("multi_select", []))
    # Formula -- extract the computed value
    if t == "formula":
        f = prop.get("formula", {})
        ftype = f.get("type", "")
        return str(f.get(ftype, "") or "")
    return ""


# ── Property type detection ────────────────────────────────────────────────────

def _get_schema() -> dict:
    """Get the property schema from the database or data source. Cached implicitly via _resolve."""
    ds_id = _resolve_data_source_id()
    # Try data_source schema first, fall back to database schema
    for endpoint in (f"{BASE}/data_sources/{ds_id}", f"{BASE}/databases/{NOTION_DATABASE_ID}"):
        try:
            resp = requests.get(endpoint, headers=_headers(), timeout=15)
            if resp.status_code == 200:
                schema = resp.json().get("properties", {})
                if schema:
                    return schema
        except Exception:
            continue
    return {}


def _detect_upload_prop_type() -> str:
    """
    Inspect the schema to determine whether the Upload property
    is a 'select', 'checkbox', or 'rich_text'. Caches the result.
    """
    global _upload_prop_type
    if _upload_prop_type:
        return _upload_prop_type

    try:
        schema = _get_schema()
        prop = schema.get(PROP_UPLOAD, {})
        ptype = prop.get("type", "checkbox")
        _upload_prop_type = ptype
        log.info(f"Upload property type detected: '{ptype}'")
        return ptype
    except Exception as e:
        log.warning(f"Could not detect Upload property type: {e} -- defaulting to 'checkbox'")
        _upload_prop_type = "checkbox"
        return "checkbox"


def _detect_status_prop_type() -> str:
    """
    Detect whether the Status property is 'status' or 'select'.
    Notion has a dedicated 'status' type distinct from 'select'.
    Using the wrong filter type causes the query to return 0 results.
    """
    global _status_prop_type
    if _status_prop_type:
        return _status_prop_type

    try:
        schema = _get_schema()
        prop = schema.get(PROP_STATUS, {})
        ptype = prop.get("type", "status")  # default to 'status' (most common)
        _status_prop_type = ptype
        log.info(f"Status property type detected: '{ptype}'")
        return ptype
    except Exception as e:
        log.warning(f"Could not detect Status property type: {e} -- defaulting to 'status'")
        _status_prop_type = "status"
        return "status"


def _build_upload_not_done_filter(prop_type: str) -> dict:
    """
    Build a Notion API filter clause that matches pages where Upload is NOT done.
    Handles select (value='No'), checkbox (false), and rich_text (contains 'no').
    """
    if prop_type == "checkbox":
        return {"property": PROP_UPLOAD, "checkbox": {"equals": False}}
    elif prop_type == "rich_text":
        return {"property": PROP_UPLOAD, "rich_text": {"does_not_contain": "Yes"}}
    else:  # select (default)
        return {"property": PROP_UPLOAD, "select": {"equals": UPLOAD_NO}}


def _build_status_filter(status_value: str) -> dict:
    """
    Build the correct filter for the Status property based on its detected type.
    Notion 'status' and 'select' types require different filter keys.
    """
    status_type = _detect_status_prop_type()
    return {"property": PROP_STATUS, status_type: {"equals": status_value}}


# ── Query ──────────────────────────────────────────────────────────────────────

def query_ready_to_upload(date_filter: list[str] | None = None) -> list[dict]:
    """
    Returns ONLY pages where:
      Layer 1 (API):    Status == "Ready to Upload"  (type auto-detected)
      Layer 2 (API):    Upload == "No" / unchecked   (type auto-detected)
      Layer 2b (API):   Upload Progress is empty     (not 'Draft Upload' or 'Uploaded')
      Layer 3 (Python): Re-confirms all fields + requires a drive.google.com link

    If date_filter is provided, only pages whose Submission Date matches
    one of the given dates (YYYY-MM-DD strings) are returned.
    """
    _check_config()
    upload_type = _detect_upload_prop_type()

    url     = _query_url()
    results = []
    cursor  = None

    # Counters for transparency
    total_fetched  = 0
    skipped_status = 0
    skipped_upload = 0
    skipped_progress = 0
    skipped_link   = 0
    skipped_name   = 0

    while True:
        # ── Layer 1 + 2: Compound server-side filter ──────────────────────────
        status_filter = _build_status_filter(STATUS_READY)

        if date_filter:
            # Day-filtered mode: Status + Upload=No + date
            # (no Upload Progress filter — user uploads manually)
            upload_filter = _build_upload_not_done_filter(upload_type)
            filter_clauses = [status_filter, upload_filter]
            if len(date_filter) == 1:
                filter_clauses.append({
                    "property": "Submission Date",
                    "date": {"equals": date_filter[0]},
                })
            else:
                filter_clauses.append({
                    "or": [
                        {"property": "Submission Date", "date": {"equals": d}}
                        for d in date_filter
                    ]
                })
            payload = {
                "filter": {"and": filter_clauses},
                "page_size": 100,
            }
        else:
            # Normal mode: Status + Upload=No
            upload_filter = _build_upload_not_done_filter(upload_type)
            payload = {
                "filter": {
                    "and": [
                        status_filter,
                        upload_filter,
                    ]
                },
                "page_size": 100,
            }
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for page in data.get("results", []):
            total_fetched += 1
            props      = page["properties"]
            page_id    = page["id"]
            video_name = _prop_value(props, PROP_VIDEO_NAME).strip()

            # ── Layer 3a: Re-confirm Status is EXACTLY "Ready to Upload" ──────
            status_val = _prop_value(props, PROP_STATUS).strip()
            if status_val != STATUS_READY:
                log.warning(
                    f"  SKIP [{video_name or page_id}]: Status='{status_val}' "
                    f"(expected '{STATUS_READY}') -- filtered client-side"
                )
                skipped_status += 1
                continue

            # ── Layer 3b: Re-confirm Upload is NOT done ───────────────────────
            upload_val = _prop_value(props, PROP_UPLOAD).strip()
            if upload_val.lower() in ("yes", "true"):
                log.info(
                    f"  SKIP [{video_name or page_id}]: Upload='{upload_val}' "
                    f"-- already marked uploaded"
                )
                skipped_upload += 1
                continue

            # ── Layer 3c: Upload Progress — logged but NOT skipped ─────────
            #    User uploads manually; progress state doesn't block fetching.
            progress_val = _prop_value(props, PROP_UPLOAD_PROGRESS).strip()
            if progress_val:
                log.info(
                    f"  NOTE [{video_name or page_id}]: Upload Progress='{progress_val}' "
                    f"-- continuing anyway (manual upload mode)"
                )

            # ── Layer 3d: Must have at least one Google Drive link ─────────
            hindi_link   = _prop_value(props, PROP_FINAL_VIDEO_HINDI_LINK).strip()
            english_link = _prop_value(props, PROP_FINAL_VIDEO_ENGLISH_LINK).strip()

            has_hindi   = "drive.google.com" in hindi_link
            has_english = "drive.google.com" in english_link

            if not has_hindi and not has_english:
                log.info(
                    f"  SKIP [{video_name or page_id}]: No Drive link "
                    f"(Hindi='{hindi_link[:60] if hindi_link else 'empty'}', "
                    f"English='{english_link[:60] if english_link else 'empty'}')"
                )
                skipped_link += 1
                continue

            # ── Layer 3e: Must have a video name ─────────────────────────────
            if not video_name:
                log.warning(f"  SKIP [page {page_id}]: Empty video name")
                skipped_name += 1
                continue

            # ── Passed all checks — enqueue one entry per available link ──────
            age_group = _prop_value(props, PROP_AGE_GROUP).strip()
            category  = _prop_value(props, PROP_CATEGORY).strip()

            link_variants = []
            if has_hindi:
                link_variants.append((hindi_link,   "___ln_Hi"))
            if has_english:
                link_variants.append((english_link, "___ln_En"))

            for drive_link, lang_suffix in link_variants:
                short_pid = page_id.replace("-", "")
                tagged_name = f"{video_name}___pg_{short_pid}{lang_suffix}"
                log.info(
                    f"  [OK] QUEUE [{tagged_name}] | "
                    f"Status='{status_val}' | Upload='{upload_val}' | "
                    f"Category={category}"
                )
                results.append({
                    "page_id":    page_id,
                    "video_name": tagged_name,
                    "age_group":  age_group,
                    "category":   category,
                    "drive_link": drive_link,
                    "status":     status_val,
                    "upload":     upload_val,
                    "lang_suffix": lang_suffix,
                })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    # ── Summary log ───────────────────────────────────────────────────────────
    log.info(
        f"\nNotion query complete:"
        f"\n  Fetched by API filter : {total_fetched}"
        f"\n  Skipped (wrong status): {skipped_status}"
        f"\n  Skipped (already done): {skipped_upload}"
        f"\n  Skipped (in progress) : {skipped_progress}"
        f"\n  Skipped (no Drive link): {skipped_link}"
        f"\n  Skipped (no name)      : {skipped_name}"
        f"\n  [OK] Ready to process    : {len(results)}"
    )
    return results


def query_available_days() -> list[dict]:
    """Fetch all 'Ready to Upload' pages and group them by Day Lable.

    Uses RELAXED filters (Status only) so every day appears in the picker,
    even if some videos have Upload Progress already set.

    Returns a sorted list of dicts:
        [{"day_label": "Day 82 — Jul 08", "day_number": "82",
          "submission_date": "2026-07-08", "video_count": 5}, ...]
    """
    _check_config()
    upload_type = _detect_upload_prop_type()

    url     = _query_url()
    cursor  = None

    day_groups: dict[str, dict] = {}  # submission_date -> info

    while True:
        status_filter = _build_status_filter(STATUS_READY)
        upload_filter = _build_upload_not_done_filter(upload_type)
        payload = {
            "filter": {
                "and": [
                    status_filter,
                    upload_filter,
                ]
            },
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
        if resp.status_code != 200:
            log.error(f"Failed to fetch available days: {resp.status_code}")
            break
        data = resp.json()

        for page in data.get("results", []):
            props = page["properties"]

            # Extract Day Lable (formula → string)
            day_lbl = _prop_value(props, "Day Lable").strip() or "(no day)"
            day_num = _prop_value(props, "Day Number").strip() or "0"
            sub_date = _prop_value(props, "Submission Date").strip() or ""

            if sub_date not in day_groups:
                day_groups[sub_date] = {
                    "day_label": day_lbl,
                    "day_number": day_num,
                    "submission_date": sub_date,
                    "video_count": 0,
                }
            day_groups[sub_date]["video_count"] += 1

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    # Sort by day number (numeric), then by date
    result = sorted(
        day_groups.values(),
        key=lambda d: (int(d["day_number"]) if d["day_number"].isdigit() else 9999, d["submission_date"]),
    )
    log.info(f"Available days: {len(result)} day(s), {sum(d['video_count'] for d in result)} total videos")
    return result


def query_failed_to_upload() -> list[dict]:
    """
    Returns pages where Status == "Failed to upload".
    Used by retry scripts to re-process previously failed videos.
    Requires a valid Drive link and video name.
    """
    _check_config()

    url     = _query_url()
    results = []
    cursor  = None

    while True:
        status_filter = _build_status_filter(STATUS_FAILED_UPLOAD)
        payload = {
            "filter": {
                "and": [
                    status_filter,
                ]
            },
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
        if resp.status_code != 200:
            log.error(f"Failed upload query failed: {resp.status_code} {resp.text[:500]}")
            break
        data = resp.json()

        for page in data.get("results", []):
            props      = page["properties"]
            page_id    = page["id"]
            video_name = _prop_value(props, PROP_VIDEO_NAME).strip()

            if not video_name:
                log.warning(f"  SKIP [page {page_id}]: Empty video name")
                continue

            hindi_link   = _prop_value(props, PROP_FINAL_VIDEO_HINDI_LINK).strip()
            english_link = _prop_value(props, PROP_FINAL_VIDEO_ENGLISH_LINK).strip()
            has_hindi   = "drive.google.com" in hindi_link
            has_english = "drive.google.com" in english_link

            if not has_hindi and not has_english:
                log.info(
                    f"  SKIP [{video_name}]: No Drive link "
                    f"(Hindi='{hindi_link[:60] if hindi_link else 'empty'}', "
                    f"English='{english_link[:60] if english_link else 'empty'}')"
                )
                continue

            age_group = _prop_value(props, PROP_AGE_GROUP).strip()
            category  = _prop_value(props, PROP_CATEGORY).strip()
            status    = _prop_value(props, PROP_STATUS).strip()
            upload    = _prop_value(props, PROP_UPLOAD).strip()

            link_variants = []
            if has_hindi:
                link_variants.append((hindi_link,   "___ln_Hi"))
            if has_english:
                link_variants.append((english_link, "___ln_En"))

            for drive_link, lang_suffix in link_variants:
                short_pid = page_id.replace("-", "")
                tagged_name = f"{video_name}___pg_{short_pid}{lang_suffix}"
                results.append({
                    "page_id":    page_id,
                    "video_name": tagged_name,
                    "age_group":  age_group,
                    "category":   category,
                    "drive_link": drive_link,
                    "status":     status,
                    "upload":     upload,
                    "lang_suffix": lang_suffix,
                })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    log.info(f"\nNotion 'Failed to upload' query: {len(results)} video(s) found.")
    return results


# ── Update ─────────────────────────────────────────────────────────────────────

def _clean_title(video_name: str) -> str:
    """Strip internal pipeline tags and produce a clean, web-safe title.

    Steps:
      1. Remove ___pg_<hex> and ___ln_Hi/___ln_En pipeline suffixes
      2. Unicode-normalize and strip Devanagari / non-ASCII characters
      3. Replace spaces with underscores
      4. Remove any remaining special characters (keep only [A-Za-z0-9_])
      5. Collapse consecutive underscores and strip leading/trailing underscores
    """
    name = video_name
    # 1. Remove ___pg_<hex> suffix
    if "___pg_" in name:
        name = name.split("___pg_")[0]
    # Remove ___ln_Hi / ___ln_En suffix (if ___pg_ wasn't present)
    if "___ln_" in name:
        name = name.split("___ln_")[0]
    # 2. Unicode-normalize, then strip all non-ASCII (Devanagari, etc.)
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    # 3. Replace spaces with underscores
    name = name.replace(" ", "_")
    # 4. Remove any remaining special characters (keep alphanumeric + underscore)
    name = re.sub(r"[^A-Za-z0-9_]", "", name)
    # 5. Collapse consecutive underscores and strip edges
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "untitled"

def _build_upload_patch(upload_date_str: str, upload_prop_type: str = "checkbox") -> dict:
    """
    Build the PATCH body to finalize a page.
    Sets Upload = True (checkbox), Upload Date, Upload Progress = 'Uploaded'.
    """
    return {"properties": {
        PROP_UPLOAD_DATE: {"date": {"start": upload_date_str}},
        PROP_UPLOAD_PROGRESS: {"select": {"name": UPLOAD_PROGRESS_REVIEWED}},
        PROP_UPLOAD: {"checkbox": True},
    }}


def mark_uploaded_in_notion(
    page_id: str,
    upload_date: str | None = None,
    video_name: str | None = None,
    lang_suffix: str | None = None,
    check_upload: bool = True,        # kept for backward-compat, always True now
    retries: int = 3,
) -> bool:
    """
    Finalize & Sync: set Upload Progress = 'first review',
    Upload = Yes, Upload Date = today, and write Hindi/English Title.
    """
    if _notion_write_blocked("mark_uploaded_in_notion"): return True
    _check_config()
    if upload_date is None:
        upload_date = date.today().isoformat()

    url = f"{BASE}/pages/{page_id}"

    # Title properties
    title_props: dict = {}
    if video_name and lang_suffix:
        web_safe_name = _clean_title(video_name)
        if lang_suffix == "___ln_Hi":
            title_props[PROP_HINDI_TITLE_ON_APP] = {
                "rich_text": [{"text": {"content": web_safe_name}}]
            }
        elif lang_suffix == "___ln_En":
            title_props[PROP_ENGLISH_TITLE_ON_APP] = {
                "rich_text": [{"text": {"content": web_safe_name}}]
            }

    for attempt in range(1, retries + 1):
        patch = _build_upload_patch(upload_date)
        patch["properties"].update(title_props)

        resp = requests.patch(url, headers=_headers(), json=patch, timeout=30)
        if resp.status_code == 200:
            title_info = ""
            if video_name and lang_suffix:
                field = "Hindi" if lang_suffix == "___ln_Hi" else "English"
                title_info = f", {field} Title='{video_name}'"
            log.info(
                f"[OK] Notion finalized: {page_id} "
                f"(Upload=Yes, Date={upload_date}, "
                f"Progress='{UPLOAD_PROGRESS_REVIEWED}'{title_info})"
            )
            return True
        else:
            log.warning(
                f"Notion PATCH attempt {attempt} failed: "
                f"{resp.status_code} {resp.text[:200]}"
            )

    log.error(f"[FAIL] Failed to update Notion page {page_id} after {retries} attempts.")
    return False


def clear_upload_progress_in_notion(page_id: str, retries: int = 3) -> bool:
    """
    Clear upload-related fields in Notion so a deleted/reset video
    can be re-downloaded by the pipeline.

    Clears:
      - Upload Progress  (select → empty)
      - Status           (status/select → 'Ready to Upload')  [type auto-detected]
      - Upload           (checkbox → False)
      - Upload Date      (date → None)
      - Hindi Title on App  (rich_text → empty)
      - English Title on App (rich_text → empty)
      - Batch ID         (rich_text → empty)

    Returns True on success.
    """
    if _notion_write_blocked("clear_upload_progress_in_notion"): return True
    _check_config()
    url = f"{BASE}/pages/{page_id}"

    status_type = _detect_status_prop_type()
    props = {
        PROP_UPLOAD_PROGRESS: {"select": None},
        PROP_STATUS: {status_type: {"name": STATUS_READY}},
        PROP_UPLOAD: {"checkbox": False},
        PROP_UPLOAD_DATE: {"date": None},
        PROP_HINDI_TITLE_ON_APP: {"rich_text": []},
        PROP_ENGLISH_TITLE_ON_APP: {"rich_text": []},
        PROP_BATCH_ID: {"rich_text": []},
    }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.patch(
                url, headers=_headers(),
                json={"properties": props}, timeout=30,
            )
            if resp.status_code == 200:
                log.info(
                    f"[OK] Notion upload progress cleared: {page_id} "
                    f"(Status='{STATUS_READY}', Upload=No, Progress=cleared)"
                )
                return True
            else:
                log.warning(
                    f"Notion clear-progress PATCH attempt {attempt}: "
                    f"{resp.status_code} {resp.text[:200]}"
                )
        except Exception as e:
            log.warning(f"Notion clear-progress PATCH attempt {attempt} error: {e}")

    log.error(f"[FAIL] Could not clear upload progress for {page_id} after {retries} attempts.")
    return False

def mark_failed_in_notion(page_id: str, retries: int = 3) -> bool:
    """
    Update Notion page to mark a failed upload:
      - Status = "Failed to upload"  (type auto-detected)
      - Upload = No / unchecked     (type auto-detected)
      - Upload Date = cleared
    Returns True on success.
    """
    if _notion_write_blocked("mark_failed_in_notion"): return True
    _check_config()
    url = f"{BASE}/pages/{page_id}"

    status_type = _detect_status_prop_type()
    upload_type = _detect_upload_prop_type()

    props = {
        PROP_STATUS: {status_type: {"name": STATUS_FAILED_UPLOAD}},
        PROP_UPLOAD_DATE: {"date": None},
    }
    # Set Upload = No/False based on detected type
    if upload_type == "checkbox":
        props[PROP_UPLOAD] = {"checkbox": False}
    else:
        props[PROP_UPLOAD] = {"select": {"name": UPLOAD_NO}}

    for attempt in range(1, retries + 1):
        try:
            resp = requests.patch(url, headers=_headers(), json={"properties": props}, timeout=30)
            if resp.status_code == 200:
                log.info(f"[OK] Notion marked FAILED: {page_id}")
                return True
            else:
                log.warning(f"Notion PATCH (fail) attempt {attempt}: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            log.warning(f"Notion PATCH (fail) attempt {attempt} error: {e}")

    log.error(f"[FAIL] Could not mark Notion page {page_id} as failed after {retries} attempts.")
    return False


def update_category_in_notion(page_id: str, new_category: str, retries: int = 3) -> bool:
    """
    Update the Category multi_select property on a Notion page.
    Keeps existing values (e.g. "Varnmala") and adds the new category
    (e.g. "Swar" or "Vyanjan") alongside it.
    Returns True on success.
    """
    if _notion_write_blocked("update_category_in_notion"): return True
    _check_config()
    url = f"{BASE}/pages/{page_id}"

    # First, read current categories to preserve them
    existing_cats = []
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 200:
            props = resp.json().get("properties", {})
            cat_prop = props.get(PROP_CATEGORY, {})
            if cat_prop.get("type") == "multi_select":
                existing_cats = [o["name"] for o in cat_prop.get("multi_select", [])]
    except Exception as e:
        log.warning(f"Could not read existing categories for {page_id}: {e}")

    # Build new list: keep existing + add new (avoid duplicates)
    all_cats = list(existing_cats)
    if new_category not in all_cats:
        all_cats.append(new_category)

    patch = {
        "properties": {
            PROP_CATEGORY: {
                "multi_select": [{"name": cat} for cat in all_cats]
            },
        }
    }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.patch(url, headers=_headers(), json=patch, timeout=30)
            if resp.status_code == 200:
                log.info(f"[OK] Notion category updated: {page_id[:12]}… → {all_cats}")
                return True
            else:
                log.warning(
                    f"Notion category PATCH attempt {attempt}: "
                    f"{resp.status_code} {resp.text[:200]}"
                )
        except Exception as e:
            log.warning(f"Notion category PATCH attempt {attempt} error: {e}")

    log.error(f"[FAIL] Could not update Notion category for {page_id} after {retries} attempts.")
    return False


def validate_connection() -> bool:
    """Quick connectivity test -- returns True if token + database are valid."""
    try:
        _check_config()
        url  = f"{BASE}/databases/{NOTION_DATABASE_ID}"
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 200:
            db   = resp.json()
            title = "".join(t.get("plain_text", "") for t in db.get("title", []))
            log.info(f"[OK] Notion connected: database '{title}'")
            return True
        else:
            log.error(f"Notion connection failed: {resp.status_code} {resp.text[:300]}")
            return False
    except Exception as e:
        log.error(f"Notion connection error: {e}")
        return False


# ── Multi-PC claim mechanism (REMOVED — single-computer mode) ─────────────────
# claim_for_upload() and release_claim() removed — not needed for single-PC use.


def mark_redo_in_notion(page_id: str, reason: str = "", retries: int = 3) -> bool:
    """
    Mark a video for re-do in Notion:
      - Re-do (checkbox) = True
      - reason for re-do (rich_text) = reason string
    Returns True on success.
    """
    if _notion_write_blocked("mark_redo_in_notion"): return True
    _check_config()
    url = f"{BASE}/pages/{page_id}"

    props = {
        PROP_REDO: {"checkbox": True},
        PROP_REDO_REASON: {
            "rich_text": [{"text": {"content": reason}}] if reason else []
        },
    }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.patch(url, headers=_headers(), json={"properties": props}, timeout=30)
            if resp.status_code == 200:
                log.info(f"[OK] Notion marked RE-DO: {page_id[:12]}… reason='{reason[:50]}'")
                return True
            else:
                log.warning(f"Notion REDO PATCH attempt {attempt}: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            log.warning(f"Notion REDO PATCH attempt {attempt} error: {e}")

    log.error(f"[FAIL] Could not mark Notion page {page_id} as re-do after {retries} attempts.")
    return False


def clear_redo_in_notion(page_id: str, retries: int = 3) -> bool:
    """
    Clear the re-do flag in Notion:
      - Re-do (checkbox) = False
      - reason for re-do (rich_text) = cleared
    Returns True on success.
    """
    if _notion_write_blocked("clear_redo_in_notion"): return True
    _check_config()
    url = f"{BASE}/pages/{page_id}"

    props = {
        PROP_REDO: {"checkbox": False},
        PROP_REDO_REASON: {"rich_text": []},
    }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.patch(url, headers=_headers(), json={"properties": props}, timeout=30)
            if resp.status_code == 200:
                log.info(f"[OK] Notion cleared RE-DO: {page_id[:12]}…")
                return True
            else:
                log.warning(f"Notion clear-REDO PATCH attempt {attempt}: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            log.warning(f"Notion clear-REDO PATCH attempt {attempt} error: {e}")

    log.error(f"[FAIL] Could not clear Notion re-do for {page_id} after {retries} attempts.")
    return False


# ── Cross-computer workflow ───────────────────────────────────────────────────

def mark_pending_review_in_notion(
    page_id: str,
    video_name: str | None = None,
    lang_suffix: str | None = None,
    batch_name: str | None = None,
    retries: int = 3,
) -> bool:
    """
    After uploading to admin: set Upload Progress = 'draft upload',
    write the Hindi/English Title on App, and store the Batch ID.

    Does NOT check the Upload checkbox or set the Upload Date —
    those are deferred until a reviewer calls finalize_in_notion().
    """
    if _notion_write_blocked("mark_pending_review_in_notion"): return True
    _check_config()
    url = f"{BASE}/pages/{page_id}"

    props: dict = {
        PROP_UPLOAD_PROGRESS: {"select": {"name": UPLOAD_PROGRESS_DRAFT}},
    }

    # Write batch name so other PCs can see which batch this belongs to
    if batch_name:
        props[PROP_BATCH_ID] = {
            "rich_text": [{"text": {"content": batch_name}}]
        }

    # Write title field based on language
    if video_name and lang_suffix:
        web_safe_name = _clean_title(video_name)
        if lang_suffix == "___ln_Hi":
            props[PROP_HINDI_TITLE_ON_APP] = {
                "rich_text": [{"text": {"content": web_safe_name}}]
            }
        elif lang_suffix == "___ln_En":
            props[PROP_ENGLISH_TITLE_ON_APP] = {
                "rich_text": [{"text": {"content": web_safe_name}}]
            }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.patch(
                url, headers=_headers(),
                json={"properties": props}, timeout=30,
            )
            if resp.status_code == 200:
                title_info = ""
                if video_name and lang_suffix:
                    field = "Hindi" if lang_suffix == "___ln_Hi" else "English"
                    title_info = f", {field} Title='{video_name}'"
                batch_info = f", Batch='{batch_name}'" if batch_name else ""
                log.info(
                    f"[OK] Notion pending review: {page_id} "
                    f"(Upload Progress='{UPLOAD_PROGRESS_DRAFT}'{title_info}{batch_info})"
                )
                return True
            else:
                log.warning(
                    f"Notion pending-review PATCH attempt {attempt}: "
                    f"{resp.status_code} {resp.text[:200]}"
                )
        except Exception as e:
            log.warning(f"Notion pending-review PATCH attempt {attempt} error: {e}")

    log.error(f"[FAIL] Could not set pending review for {page_id} after {retries} attempts.")
    return False


def query_pending_review() -> list[dict]:
    """
    Returns pages where Upload Progress == 'draft upload'.
    These are pages uploaded to the CMS but not yet reviewed.
    """
    _check_config()

    url     = _query_url()
    results = []
    cursor  = None

    while True:
        payload = {
            "filter": {
                "and": [
                    {
                        "property": PROP_UPLOAD_PROGRESS,
                        "select":   {"equals": UPLOAD_PROGRESS_DRAFT},
                    },
                    {
                        "property": PROP_UPLOAD,
                        "checkbox": {"equals": False},
                    },
                ]
            },
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
        if resp.status_code != 200:
            log.error(f"Pending review query failed: {resp.status_code} {resp.text[:500]}")
            return results
        data = resp.json()

        for page in data.get("results", []):
            props      = page["properties"]
            page_id    = page["id"]
            video_name = _prop_value(props, PROP_VIDEO_NAME).strip()
            hindi_title  = _prop_value(props, PROP_HINDI_TITLE_ON_APP).strip()
            english_title = _prop_value(props, PROP_ENGLISH_TITLE_ON_APP).strip()
            age_group  = _prop_value(props, PROP_AGE_GROUP).strip()
            category   = _prop_value(props, PROP_CATEGORY).strip()
            batch_id   = _prop_value(props, PROP_BATCH_ID).strip()

            results.append({
                "page_id":       page_id,
                "video_name":    video_name,
                "hindi_title":   hindi_title,
                "english_title": english_title,
                "age_group":     age_group,
                "category":      category,
                "batch_id":      batch_id,
            })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    log.info(f"Pending review query: {len(results)} page(s) found.")
    return results


def finalize_in_notion(
    page_id: str,
    upload_date: str | None = None,
    retries: int = 3,
) -> bool:
    """
    Reviewer finalizes a page:
      - Set Upload Progress = 'Uploaded'
      - Set Upload = Yes + Upload Date = today
    """
    if _notion_write_blocked("finalize_in_notion"): return True
    _check_config()
    if upload_date is None:
        upload_date = date.today().isoformat()

    url = f"{BASE}/pages/{page_id}"

    for attempt in range(1, retries + 1):
        patch = _build_upload_patch(upload_date)
        resp = requests.patch(url, headers=_headers(), json=patch, timeout=30)
        if resp.status_code == 200:
            log.info(
                f"[OK] Notion finalized: {page_id} "
                f"(Upload=Yes, Date={upload_date}, Progress='{UPLOAD_PROGRESS_REVIEWED}')"
            )
            return True
        else:
            log.warning(
                f"Notion finalize PATCH attempt {attempt}: "
                f"{resp.status_code} {resp.text[:200]}"
            )

    log.error(f"[FAIL] Could not finalize Notion page {page_id} after {retries} attempts.")
    return False


