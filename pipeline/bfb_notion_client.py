"""
bfb_notion_client.py -- Notion API client for the BabyBillion Bottle-Fed Billionaires database.

This queries the PRODUCTION database (25663e60...) which has teacher-based views
(Ms Pranika, Ms Nidhi, Ms Isha, Ms Donna, Ms Joy).

Each teacher has their own status property. "Ready To Upload" in that property
means the video is ready for download from "Final Draft Hinglish" / "Final Draft English".
"""
from __future__ import annotations

import re
import logging
import time
import requests
from datetime import date
from config import (
    NOTION_TOKEN,
    BFB_DATABASE_ID, BFB_TEACHERS,
    BFB_PROP_TITLE, BFB_PROP_FINAL_DRAFT_HINGLISH, BFB_PROP_FINAL_DRAFT_ENGLISH,
    BFB_PROP_CATEGORY, BFB_PROP_AGE_GROUP,
    BFB_PROP_UPLOAD_DATE, BFB_PROP_MOVED_TO_UPLOAD,
    NOTION_READ_ONLY,
)

log = logging.getLogger(__name__)

NOTION_VERSION = "2025-09-03"
BASE = "https://api.notion.com/v1"

# ── Cached data source ID ─────────────────────────────────────────────────────
_bfb_data_source_id = None
_bfb_use_data_source_url = False


def _headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type":  "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _resolve_bfb_data_source() -> str:
    """Resolve the data source ID for the BFB database."""
    global _bfb_data_source_id, _bfb_use_data_source_url

    if _bfb_data_source_id:
        return _bfb_data_source_id

    # Try fetching database metadata to find data sources
    url = f"{BASE}/databases/{BFB_DATABASE_ID}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            data_sources = data.get("data_sources", [])
            if data_sources:
                # Pick the first data source that has content
                for ds in data_sources:
                    ds_id = ds.get("id")
                    if ds_id:
                        test_url = f"{BASE}/data_sources/{ds_id}/query"
                        test_resp = requests.post(test_url, headers=_headers(),
                                                  json={"page_size": 1}, timeout=15)
                        if test_resp.status_code == 200 and test_resp.json().get("results"):
                            _bfb_data_source_id = ds_id
                            _bfb_use_data_source_url = True
                            log.info(f"[BFB] Resolved data source: {ds_id}")
                            return _bfb_data_source_id

                # If no data source had results, use the first one
                _bfb_data_source_id = data_sources[0].get("id", BFB_DATABASE_ID)
                _bfb_use_data_source_url = True
                return _bfb_data_source_id
    except Exception as e:
        log.warning(f"[BFB] Could not resolve data source: {e}")

    # Fallback: use database ID directly
    _bfb_data_source_id = BFB_DATABASE_ID
    _bfb_use_data_source_url = False
    return _bfb_data_source_id


def _query_url() -> str:
    ds_id = _resolve_bfb_data_source()
    if _bfb_use_data_source_url:
        return f"{BASE}/data_sources/{ds_id}/query"
    else:
        return f"{BASE}/databases/{ds_id}/query"


# ── Property extractors ──────────────────────────────────────────────────────

def _prop_value(properties: dict, name: str) -> str:
    """Generic extractor -- handles title, rich_text, select, url, checkbox, status."""
    prop = properties.get(name)
    if prop is None:
        return ""
    t = prop.get("type", "")
    if t == "title":
        parts = prop.get("title", [])
        return "".join(p.get("plain_text", "") for p in parts).strip()
    if t == "rich_text":
        parts = prop.get("rich_text", [])
        return "".join(p.get("plain_text", "") for p in parts).strip()
    if t == "select":
        sel = prop.get("select")
        return sel["name"] if sel else ""
    if t == "status":
        s = prop.get("status")
        return s["name"] if s else ""
    if t == "url":
        return prop.get("url") or ""
    if t == "checkbox":
        return "Yes" if prop.get("checkbox", False) else "No"
    if t == "date":
        d = prop.get("date")
        return d["start"] if d else ""
    if t == "multi_select":
        return ", ".join(o["name"] for o in prop.get("multi_select", []))
    if t == "formula":
        f = prop.get("formula", {})
        ftype = f.get("type", "")
        return str(f.get(ftype, "") or "")
    return ""


# ── Query for BFB videos ─────────────────────────────────────────────────────

def query_bfb_ready_to_upload(teacher: str | None = None) -> list[dict]:
    """
    Query the BFB database for videos where a teacher's status = "Ready To Upload".

    If teacher is None, queries ALL teachers and deduplicates.
    Returns a list of dicts compatible with the existing pipeline format.
    """
    if not NOTION_TOKEN:
        raise ValueError("NOTION_TOKEN is not set.")

    url = _query_url()
    results = []
    seen_page_ids = set()  # deduplicate across teachers

    teachers_to_query = [teacher] if teacher else BFB_TEACHERS

    for t_name in teachers_to_query:
        cursor = None
        while True:
            # Build filter: teacher status = "Ready To Upload"
            # Notion teacher properties can be 'status' or 'select' type
            # Try status first (most common for these fields)
            payload = {
                "filter": {
                    "property": t_name,
                    "status": {"equals": "Ready To Upload"},
                },
                "page_size": 100,
            }
            if cursor:
                payload["start_cursor"] = cursor

            try:
                resp = requests.post(url, headers=_headers(), json=payload, timeout=30)

                # If status filter fails, try select filter
                if resp.status_code == 400:
                    payload["filter"] = {
                        "property": t_name,
                        "select": {"equals": "Ready To Upload"},
                    }
                    resp = requests.post(url, headers=_headers(), json=payload, timeout=30)

                if resp.status_code != 200:
                    log.warning(f"[BFB] Query for {t_name} failed: {resp.status_code} {resp.text[:200]}")
                    break

                data = resp.json()
            except Exception as e:
                log.error(f"[BFB] Request error for {t_name}: {e}")
                break

            for page in data.get("results", []):
                page_id = page["id"]
                if page_id in seen_page_ids:
                    continue
                seen_page_ids.add(page_id)

                props = page["properties"]
                video_name = _prop_value(props, BFB_PROP_TITLE).strip()

                if not video_name:
                    log.warning(f"[BFB] SKIP page {page_id}: no title")
                    continue

                # Extract download links
                hinglish_link = _prop_value(props, BFB_PROP_FINAL_DRAFT_HINGLISH).strip()
                english_link  = _prop_value(props, BFB_PROP_FINAL_DRAFT_ENGLISH).strip()

                has_hinglish = "drive.google.com" in hinglish_link or "f.io" in hinglish_link
                has_english  = "drive.google.com" in english_link or "f.io" in english_link

                if not has_hinglish and not has_english:
                    log.info(f"[BFB] SKIP [{video_name}]: No download link")
                    continue

                # Extract metadata
                category  = _prop_value(props, BFB_PROP_CATEGORY).strip()
                age_group = _prop_value(props, BFB_PROP_AGE_GROUP).strip()
                teacher_status = _prop_value(props, t_name).strip()

                # Build link variants (matching existing pipeline format)
                link_variants = []
                if has_hinglish:
                    link_variants.append((hinglish_link, "___ln_Hi"))
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
                        "status":     teacher_status,
                        "upload":     "No",
                        "lang_suffix": lang_suffix,
                        "teacher":    t_name,
                        "source_db":  "bfb",
                    })

            time.sleep(0.35)  # rate limit

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    log.info(f"[BFB] Query complete: {len(results)} video variants across {len(seen_page_ids)} pages")
    return results


def query_bfb_teachers_summary() -> list[dict]:
    """
    Return a summary of video counts per teacher in "Ready To Upload" status.
    Returns: [{"teacher": "Ms Pranika", "video_count": 15}, ...]
    """
    if not NOTION_TOKEN:
        raise ValueError("NOTION_TOKEN is not set.")

    url = _query_url()
    summaries = []

    for t_name in BFB_TEACHERS:
        count = 0
        cursor = None
        while True:
            payload = {
                "filter": {
                    "property": t_name,
                    "status": {"equals": "Ready To Upload"},
                },
                "page_size": 100,
            }
            if cursor:
                payload["start_cursor"] = cursor

            try:
                resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
                if resp.status_code == 400:
                    payload["filter"] = {
                        "property": t_name,
                        "select": {"equals": "Ready To Upload"},
                    }
                    resp = requests.post(url, headers=_headers(), json=payload, timeout=30)

                if resp.status_code != 200:
                    break

                data = resp.json()
                count += len(data.get("results", []))

                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")
            except Exception:
                break

            time.sleep(0.35)

        summaries.append({"teacher": t_name, "video_count": count})

    return summaries


def mark_bfb_moved_to_upload(page_id: str) -> bool:
    """Set 'Moved To Upload' checkbox to True and 'Upload Date' to today on a BFB page."""
    if NOTION_READ_ONLY:
        log.info(f"[BFB] READ-ONLY: Would mark {page_id} as moved to upload")
        return True

    url = f"{BASE}/pages/{page_id}"
    payload = {
        "properties": {
            BFB_PROP_MOVED_TO_UPLOAD: {"checkbox": True},
            BFB_PROP_UPLOAD_DATE: {
                "date": {"start": date.today().isoformat()}
            },
        }
    }
    try:
        resp = requests.patch(url, headers=_headers(), json=payload, timeout=15)
        if resp.status_code == 200:
            log.info(f"[BFB] Marked {page_id} as moved to upload")
            return True
        else:
            log.error(f"[BFB] Failed to mark {page_id}: {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        log.error(f"[BFB] Error marking {page_id}: {e}")
        return False
