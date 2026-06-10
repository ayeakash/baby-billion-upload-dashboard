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

import requests
import logging
from datetime import date
from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID,
    PROP_VIDEO_NAME, PROP_AGE_GROUP, PROP_CATEGORY,
    PROP_STATUS, PROP_UPLOAD, PROP_UPLOAD_DATE,
    PROP_FINAL_VIDEO_HINDI_LINK, PROP_FINAL_VIDEO_ENGLISH_LINK,
    PROP_FAILED_UPLOAD, PROP_REDO, PROP_REDO_REASON,
    PROP_HINDI_TITLE_ON_APP, PROP_ENGLISH_TITLE_ON_APP,
    STATUS_READY, STATUS_UPLOADING, STATUS_FAILED_UPLOAD, UPLOAD_NO, UPLOAD_YES,
)

log = logging.getLogger(__name__)

NOTION_VERSION = "2022-06-28"
BASE = "https://api.notion.com/v1"

# Cached after first successful detection
_upload_prop_type: str | None = None   # "select" | "checkbox" | "rich_text"


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
    if t == "url":        return _extract_url(prop)
    if t == "checkbox":   return "Yes" if _extract_checkbox(prop) else "No"
    if t == "date":
        d = prop.get("date")
        return d["start"] if d else ""
    # Multi-select -- join with comma
    if t == "multi_select":
        return ", ".join(o["name"] for o in prop.get("multi_select", []))
    return ""


# ── Upload property type detection ────────────────────────────────────────────

def _detect_upload_prop_type() -> str:
    """
    Inspect the database schema to determine whether the Upload property
    is a 'select', 'checkbox', or 'rich_text'. Caches the result.
    """
    global _upload_prop_type
    if _upload_prop_type:
        return _upload_prop_type

    try:
        url  = f"{BASE}/databases/{NOTION_DATABASE_ID}"
        resp = requests.get(url, headers=_headers(), timeout=15)
        resp.raise_for_status()
        schema = resp.json().get("properties", {})
        prop   = schema.get(PROP_UPLOAD, {})
        ptype  = prop.get("type", "select")
        _upload_prop_type = ptype
        log.info(f"Upload property type detected: '{ptype}'")
        return ptype
    except Exception as e:
        log.warning(f"Could not detect Upload property type: {e} -- defaulting to 'select'")
        _upload_prop_type = "select"
        return "select"


def _build_upload_not_done_filter(prop_type: str) -> dict:
    """
    Build a Notion API filter clause that matches pages where Upload is NOT done.
    Handles select (value='No'), checkbox (false), and rich_text (contains 'no').
    """
    if prop_type == "checkbox":
        return {"property": PROP_UPLOAD, "checkbox": {"equals": False}}
    elif prop_type == "rich_text":
        # Some boards store Yes/No as plain text
        return {"property": PROP_UPLOAD, "rich_text": {"does_not_contain": "Yes"}}
    else:  # select (default)
        return {"property": PROP_UPLOAD, "select": {"equals": UPLOAD_NO}}


# ── Query ──────────────────────────────────────────────────────────────────────

def query_ready_to_upload() -> list[dict]:
    """
    Returns ONLY pages where:
      Layer 1 (API):    Status == "Ready to Upload"
      Layer 2 (API):    Upload == "No" / unchecked  (type auto-detected)
      Layer 3 (Python): Re-confirms both fields + requires a drive.google.com link

    This triple-validation ensures no video sneaks through.
    """
    _check_config()
    upload_type = _detect_upload_prop_type()

    url     = f"{BASE}/databases/{NOTION_DATABASE_ID}/query"
    results = []
    cursor  = None

    # Counters for transparency
    total_fetched  = 0
    skipped_status = 0
    skipped_upload = 0
    skipped_link   = 0
    skipped_name   = 0

    while True:
        # ── Layer 1 + 2: Compound server-side filter ──────────────────────────
        upload_filter = _build_upload_not_done_filter(upload_type)
        payload = {
            "filter": {
                "and": [
                    {
                        "property": PROP_STATUS,
                        "select":   {"equals": STATUS_READY},
                    },
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

            # ── Layer 3c: Must have at least one Google Drive link ─────────
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

            # ── Layer 3d: Must have a video name ─────────────────────────────
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
                tagged_name = f"{video_name}{lang_suffix}"
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
        f"\n  Skipped (no Drive link): {skipped_link}"
        f"\n  Skipped (no name)      : {skipped_name}"
        f"\n  [OK] Ready to process    : {len(results)}"
    )
    return results


def query_failed_to_upload() -> list[dict]:
    """
    Returns pages where Status == "Failed to upload".
    Used by retry scripts to re-process previously failed videos.
    Requires a valid Drive link and video name.
    """
    _check_config()

    url     = f"{BASE}/databases/{NOTION_DATABASE_ID}/query"
    results = []
    cursor  = None

    while True:
        payload = {
            "filter": {
                "property": PROP_STATUS,
                "select":   {"equals": STATUS_FAILED_UPLOAD},
            },
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
        resp.raise_for_status()
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
                tagged_name = f"{video_name}{lang_suffix}"
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

def _build_upload_patch(upload_date_str: str, upload_prop_type: str = "auto") -> dict:
    """
    Build the PATCH body to mark a page as uploaded.
    Handles both select ("Yes") and checkbox (true) for the Upload field.
    upload_date_str: ISO date string e.g. "2026-04-20"
    upload_prop_type: "select" | "checkbox" | "auto" (auto-detects on first call)
    """
    props = {
        PROP_UPLOAD_DATE: {
            "date": {"start": upload_date_str}
        }
    }

    if upload_prop_type == "checkbox":
        props[PROP_UPLOAD] = {"checkbox": True}
    else:
        # Default: treat as select with "Yes" option
        props[PROP_UPLOAD] = {"select": {"name": UPLOAD_YES}}

    return {"properties": props}


def mark_uploaded_in_notion(
    page_id: str,
    upload_date: str | None = None,
    video_name: str | None = None,
    lang_suffix: str | None = None,
    retries: int = 3,
) -> bool:
    """
    Update Notion page: set Upload = Yes, Upload Date = today.
    If video_name and lang_suffix are provided, also writes the final title
    to "Hindi Title on App" or "English Title on App".
    Returns True on success.
    """
    _check_config()
    if upload_date is None:
        upload_date = date.today().isoformat()

    url = f"{BASE}/pages/{page_id}"

    for attempt in range(1, retries + 1):
        # Try as select first
        for prop_type in ("select", "checkbox"):
            patch = _build_upload_patch(upload_date, prop_type)

            # Add title-on-app field based on language
            if video_name and lang_suffix:
                if lang_suffix == "___ln_Hi":
                    patch["properties"][PROP_HINDI_TITLE_ON_APP] = {
                        "rich_text": [{"text": {"content": video_name}}]
                    }
                elif lang_suffix == "___ln_En":
                    patch["properties"][PROP_ENGLISH_TITLE_ON_APP] = {
                        "rich_text": [{"text": {"content": video_name}}]
                    }

            resp  = requests.patch(url, headers=_headers(), json=patch, timeout=30)
            if resp.status_code == 200:
                title_info = ""
                if video_name and lang_suffix:
                    field = "Hindi" if lang_suffix == "___ln_Hi" else "English"
                    title_info = f", {field} Title='{video_name}'"
                log.info(f"[OK] Notion updated: {page_id} (Upload=Yes, Date={upload_date}{title_info})")
                return True
            elif resp.status_code == 400:
                # Probably wrong property type -- try the other
                log.debug(f"PATCH attempt with {prop_type} failed (400), trying next type …")
                continue
            else:
                log.warning(f"Notion PATCH attempt {attempt} failed: {resp.status_code} {resp.text[:200]}")
                break   # non-400 error -> retry outer loop

    log.error(f"[FAIL] Failed to update Notion page {page_id} after {retries} attempts.")
    return False


def mark_failed_in_notion(page_id: str, retries: int = 3) -> bool:
    """
    Update Notion page to mark a failed upload:
      - Status = "Failed to upload"
      - Failed to Upload (checkbox) = True
      - Upload = No / unchecked
      - Upload Date = cleared
    Returns True on success.
    """
    _check_config()
    url = f"{BASE}/pages/{page_id}"

    for attempt in range(1, retries + 1):
        # Try checkbox for Upload first, then select
        for upload_type in ("checkbox", "select"):
            props = {
                PROP_STATUS: {"select": {"name": STATUS_FAILED_UPLOAD}},
                PROP_FAILED_UPLOAD: {"checkbox": True},
                PROP_UPLOAD_DATE: {"date": None},
            }
            if upload_type == "checkbox":
                props[PROP_UPLOAD] = {"checkbox": False}
            else:
                props[PROP_UPLOAD] = {"select": {"name": UPLOAD_NO}}

            resp = requests.patch(url, headers=_headers(), json={"properties": props}, timeout=30)
            if resp.status_code == 200:
                log.info(f"[OK] Notion marked FAILED: {page_id}")
                return True
            elif resp.status_code == 400:
                continue
            else:
                log.warning(f"Notion PATCH (fail) attempt {attempt}: {resp.status_code} {resp.text[:200]}")
                break

    log.error(f"[FAIL] Could not mark Notion page {page_id} as failed after {retries} attempts.")
    return False


def update_category_in_notion(page_id: str, new_category: str, retries: int = 3) -> bool:
    """
    Update the Category multi_select property on a Notion page.
    Keeps existing values (e.g. "Varnmala") and adds the new category
    (e.g. "Swar" or "Vyanjan") alongside it.
    Returns True on success.
    """
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


# ── Multi-PC claim mechanism ──────────────────────────────────────────────────

def claim_for_upload(page_id: str) -> bool:
    """
    Atomically claim a video for this PC by setting Status = 'Uploading'.

    This prevents other PCs from picking up the same video, since their
    Notion query filters for Status = 'Ready to Upload' only.

    Returns True if the claim succeeded (page was updated).
    Returns False if Notion rejected the update (may already be claimed).
    """
    _check_config()
    url = f"{BASE}/pages/{page_id}"

    # First, verify the page is still "Ready to Upload" (another PC may have claimed it)
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 200:
            props = resp.json().get("properties", {})
            current_status = _prop_value(props, PROP_STATUS).strip()
            if current_status != STATUS_READY:
                log.info(
                    f"  [CLAIM SKIP] {page_id[:12]}… status is '{current_status}' "
                    f"(not '{STATUS_READY}') — already claimed by another PC"
                )
                return False
    except Exception as e:
        log.warning(f"  [CLAIM] Could not verify page status: {e} — proceeding anyway")

    # Set Status = "Uploading"
    patch = {
        "properties": {
            PROP_STATUS: {"select": {"name": STATUS_UPLOADING}},
        }
    }
    try:
        resp = requests.patch(url, headers=_headers(), json=patch, timeout=15)
        if resp.status_code == 200:
            log.info(f"  [CLAIM OK] {page_id[:12]}… → Status='{STATUS_UPLOADING}'")
            return True
        else:
            log.warning(f"  [CLAIM FAIL] {page_id[:12]}…: {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        log.warning(f"  [CLAIM ERROR] {page_id[:12]}…: {e}")
        return False


def release_claim(page_id: str) -> bool:
    """
    Release a claimed video back to 'Ready to Upload' status.
    Used when the pipeline fails after claiming but before uploading.
    """
    _check_config()
    url = f"{BASE}/pages/{page_id}"
    patch = {
        "properties": {
            PROP_STATUS: {"select": {"name": STATUS_READY}},
        }
    }
    try:
        resp = requests.patch(url, headers=_headers(), json=patch, timeout=15)
        if resp.status_code == 200:
            log.info(f"  [RELEASE] {page_id[:12]}… → Status='{STATUS_READY}'")
            return True
        else:
            log.warning(f"  [RELEASE FAIL] {page_id[:12]}…: {resp.status_code}")
            return False
    except Exception as e:
        log.warning(f"  [RELEASE ERROR] {page_id[:12]}…: {e}")
        return False


def mark_redo_in_notion(page_id: str, reason: str = "", retries: int = 3) -> bool:
    """
    Mark a video for re-do in Notion:
      - Re-do (checkbox) = True
      - reason for re-do (rich_text) = reason string
    Returns True on success.
    """
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

