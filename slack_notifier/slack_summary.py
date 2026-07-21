#!/usr/bin/env python3
"""
slack_summary.py — Nightly Slack summary for the Baby Billion content pipeline.

Queries the Notion database, counts videos by status, and sends a
formatted summary to Slack via an Incoming Webhook.

Usage:
    python slack_summary.py              # Send to Slack
    python slack_summary.py --dry-run    # Preview in terminal (no Slack post)
    python slack_summary.py --test       # Send a test ping to verify webhook
"""
from __future__ import annotations

import sys
import os
import json
import logging
import argparse
import requests
from datetime import date, datetime, timedelta, timezone
from collections import Counter

# IST timezone (UTC+5:30) — ensures correct "today" even on UTC servers
IST = timezone(timedelta(hours=5, minutes=30))

# ── Load credentials ──────────────────────────────────────────────────────────
try:
    import credentials as _creds
    _get = lambda key, default="": getattr(_creds, key, None) or os.environ.get(key, default)
except ImportError:
    _get = lambda key, default="": os.environ.get(key, default)

SLACK_WEBHOOK_URL  = _get("SLACK_WEBHOOK_URL")
NOTION_TOKEN       = _get("NOTION_TOKEN")
NOTION_DATABASE_ID = _get("NOTION_DATABASE_ID")

# ── Configuration ─────────────────────────────────────────────────────────────

NOTION_VERSION = "2025-09-03"
BASE = "https://api.notion.com/v1"

# ┌────────────────────────────────────────────────────────────────────────────┐
# │  STATUS MAPPING                                                            │
# │  Left  = label shown in the Slack message                                  │
# │  Right = list of Notion "Status" property values to count                  │
# │                                                                            │
# │  These are mapped to the actual status values in the Notion database.      │
# │  Edit if your Notion status names change.                                  │
# │                                                                            │
# │  Actual statuses in DB (as of Jul 2026):                                   │
# │    Uploaded(2984), Blocker(102), Audio Fix(89), Approved(84),              │
# │    Topic Assigned(57), Review(38), Audio Done(33), WIP(21),                │
# │    Correction(19), Ready to Upload(19), Audio Waiting list(7),             │
# │    Audio Wip(3), Failed(1)                                                 │
# └────────────────────────────────────────────────────────────────────────────┘

STATUS_MAP: dict[str, list[str]] = {
    "Ready to upload":                ["Ready to Upload"],
    "Approval pending [After audio]": ["Audio Done"],
    "Audio pending":                  ["Audio Waiting list", "Audio Wip"],
    "Corrections pending":            ["Correction"],
    "Review pending":                 ["Review"],
    "Content WIP":                    ["WIP"],
}

# Status values that mean "uploaded" (used for total + WTD/MTD counts)
UPLOADED_STATUSES = ["Uploaded", "uploaded"]

# Weekly goal — change this number as needed
WEEKLY_GOAL = 250

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("slack_summary")


# ══════════════════════════════════════════════════════════════════════════════
#  Notion helpers
# ══════════════════════════════════════════════════════════════════════════════

_data_source_id: str | None = None
_use_data_source_url: bool = True


def _headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type":  "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _resolve_data_source_id() -> str:
    """Discover the data source ID (Notion API 2025-09-03)."""
    global _data_source_id, _use_data_source_url
    if _data_source_id:
        return _data_source_id

    url = f"{BASE}/databases/{NOTION_DATABASE_ID}"
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    db = resp.json()
    data_sources = db.get("data_sources", [])

    if not data_sources:
        _data_source_id = NOTION_DATABASE_ID
        _use_data_source_url = False
        return _data_source_id

    for ds in data_sources:
        ds_id = ds.get("id")
        if ds_id:
            test_url = f"{BASE}/data_sources/{ds_id}/query"
            test_resp = requests.post(test_url, headers=_headers(), json={"page_size": 1}, timeout=15)
            if test_resp.status_code == 200 and test_resp.json().get("results"):
                _data_source_id = ds_id
                _use_data_source_url = True
                return _data_source_id

    _data_source_id = data_sources[0].get("id", NOTION_DATABASE_ID)
    _use_data_source_url = True
    return _data_source_id


def _query_url() -> str:
    ds_id = _resolve_data_source_id()
    if _use_data_source_url:
        return f"{BASE}/data_sources/{ds_id}/query"
    return f"{BASE}/databases/{ds_id}/query"


def _prop_value(properties: dict, name: str) -> str:
    """Generic Notion property extractor."""
    prop = properties.get(name)
    if prop is None:
        return ""
    t = prop.get("type", "")
    if t == "title":
        return "".join(p.get("plain_text", "") for p in prop.get("title", [])).strip()
    if t == "rich_text":
        return "".join(p.get("plain_text", "") for p in prop.get("rich_text", [])).strip()
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


# ══════════════════════════════════════════════════════════════════════════════
#  Data collection
# ══════════════════════════════════════════════════════════════════════════════

def fetch_all_pages() -> list[dict]:
    """Fetch ALL pages from the Notion database (no filter)."""
    url = _query_url()
    pages = []
    cursor = None

    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for page in data.get("results", []):
            props = page["properties"]
            hindi_link = _prop_value(props, "Final Video Hindi Link").strip()
            english_link = _prop_value(props, "Final Video English Link").strip()
            pages.append({
                "status":      _prop_value(props, "Status"),
                "upload":      _prop_value(props, "Upload"),
                "upload_date": _prop_value(props, "Upload Date"),
                "has_hindi":   bool(hindi_link),
                "has_english": bool(english_link),
            })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    log.info(f"Fetched {len(pages)} total pages from Notion")
    return pages


def _compute_for_lang(pages: list[dict], lang_key: str) -> dict:
    """Compute summary numbers for a specific language.
    lang_key is 'has_hindi' or 'has_english'.
    Only counts pages where that language link is present.
    """
    today = datetime.now(IST).date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    lang_pages = [p for p in pages if p.get(lang_key)]

    # Count statuses
    status_counter: Counter = Counter()
    for page in lang_pages:
        s = page["status"].strip()
        if s:
            status_counter[s] += 1

    # Count uploads by date
    today_uploaded = 0
    wtd_uploaded = 0
    mtd_uploaded = 0

    for page in lang_pages:
        upload_date_str = page["upload_date"].strip()
        if not upload_date_str:
            continue
        try:
            ud = datetime.strptime(upload_date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if ud == today:
            today_uploaded += 1
        if ud >= week_start:
            wtd_uploaded += 1
        if ud >= month_start:
            mtd_uploaded += 1

    # Map statuses to summary labels
    summary_counts = {}
    for label, notion_statuses in STATUS_MAP.items():
        count = sum(status_counter.get(s, 0) for s in notion_statuses)
        summary_counts[label] = count

    return {
        "today_uploaded": today_uploaded,
        "summary_counts": summary_counts,
        "wtd_uploaded": wtd_uploaded,
        "mtd_uploaded": mtd_uploaded,
        "total": len(lang_pages),
    }


def compute_summary(pages: list[dict]) -> dict:
    """Compute summary numbers overall and per-language."""
    today = datetime.now(IST).date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    # Overall status counter
    status_counter: Counter = Counter()
    for page in pages:
        s = page["status"].strip()
        if s:
            status_counter[s] += 1

    # Overall uploads by date
    today_uploaded = 0
    wtd_uploaded = 0
    mtd_uploaded = 0

    for page in pages:
        upload_date_str = page["upload_date"].strip()
        if not upload_date_str:
            continue
        try:
            ud = datetime.strptime(upload_date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if ud == today:
            today_uploaded += 1
        if ud >= week_start:
            wtd_uploaded += 1
        if ud >= month_start:
            mtd_uploaded += 1

    # Overall status summary
    summary_counts = {}
    for label, notion_statuses in STATUS_MAP.items():
        count = sum(status_counter.get(s, 0) for s in notion_statuses)
        summary_counts[label] = count

    # Per-language breakdowns
    hindi = _compute_for_lang(pages, "has_hindi")
    english = _compute_for_lang(pages, "has_english")

    return {
        "today_uploaded": today_uploaded,
        "summary_counts": summary_counts,
        "weekly_goal": WEEKLY_GOAL,
        "wtd_uploaded": wtd_uploaded,
        "mtd_uploaded": mtd_uploaded,
        "total_pages": len(pages),
        "status_counter": dict(status_counter),
        "hindi": hindi,
        "english": english,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Message formatting
# ══════════════════════════════════════════════════════════════════════════════

def _format_lang_section(lang_name: str, lang_data: dict, weekly_goal: int) -> str:
    """Format a single language section."""
    sc = lang_data["summary_counts"]
    lines = [
        f"*{lang_name}*",
        f"Uploaded Today - *{lang_data['today_uploaded']}*",
        f"Ready to upload - *{sc.get('Ready to upload', 0)}*",
        "",
        f"This week's goal - *{weekly_goal}*",
        f"WTD content uploaded - *{lang_data['wtd_uploaded']}*",
        f"MTD content uploaded - *{lang_data['mtd_uploaded']}*",
    ]
    return "\n".join(lines)


def format_slack_message(summary: dict) -> dict:
    """Build a Slack Block Kit message payload."""
    today_str = datetime.now(IST).date().strftime("%d %B %Y")

    hindi_section = _format_lang_section("Hindi", summary["hindi"], summary["weekly_goal"])
    english_section = _format_lang_section("English", summary["english"], summary["weekly_goal"])

    # Total [Hindi + English]
    total_today = summary["hindi"]["today_uploaded"] + summary["english"]["today_uploaded"]
    total_wtd = summary["hindi"]["wtd_uploaded"] + summary["english"]["wtd_uploaded"]
    total_mtd = summary["hindi"]["mtd_uploaded"] + summary["english"]["mtd_uploaded"]

    total_section = "\n".join([
        "*Total Uploaded Videos [Hindi + English]*",
        f"Uploaded Today - *{total_today}*",
        f"WTD content uploaded - *{total_wtd}*",
        f"MTD content uploaded - *{total_mtd}*",
    ])

    # Block Kit format
    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Daily Summary - {today_str}",
                    "emoji": False,
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": hindi_section,
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": english_section,
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": total_section,
                }
            },
            {
                "type": "divider"
            },
        ],
        # Fallback text for notifications
        "text": f"Daily Summary - {today_str}: Total {total_today} uploaded today (Hindi {summary['hindi']['today_uploaded']} + English {summary['english']['today_uploaded']})",
    }

    return payload


def _format_lang_plain(lang_name: str, lang_data: dict, weekly_goal: int) -> list[str]:
    """Format a single language section as plain text lines."""
    sc = lang_data["summary_counts"]
    return [
        f"  [{lang_name}]",
        f"  Uploaded Today               {lang_data['today_uploaded']}",
        f"  Ready to upload              {sc.get('Ready to upload', 0)}",
        "",
        f"  This week's goal             {weekly_goal}",
        f"  WTD content uploaded          {lang_data['wtd_uploaded']}",
        f"  MTD content uploaded          {lang_data['mtd_uploaded']}",
    ]


def format_plain_text(summary: dict) -> str:
    """Format the summary as plain text for --dry-run output."""
    today_str = datetime.now(IST).date().strftime("%d %B %Y")

    lines = [
        f"{'=' * 50}",
        f"  Daily Summary - {today_str}",
        f"{'=' * 50}",
        "",
    ]
    lines += _format_lang_plain("Hindi", summary["hindi"], summary["weekly_goal"])
    lines += ["", f"{'-' * 50}", ""]
    lines += _format_lang_plain("English", summary["english"], summary["weekly_goal"])

    total_today = summary["hindi"]["today_uploaded"] + summary["english"]["today_uploaded"]
    total_wtd = summary["hindi"]["wtd_uploaded"] + summary["english"]["wtd_uploaded"]
    total_mtd = summary["hindi"]["mtd_uploaded"] + summary["english"]["mtd_uploaded"]
    lines += ["", f"{'-' * 50}", ""]
    lines += [
        "  [Total Uploaded Videos - Hindi + English]",
        f"  Uploaded Today    {total_today}",
        f"  WTD content uploaded          {total_wtd}",
        f"  MTD content uploaded          {total_mtd}",
    ]
    lines += [
        "",
        f"{'-' * 50}",
        f"  Total pages in database: {summary['total_pages']}",
        "",
        "  All statuses found in Notion:",
    ]
    for status, count in sorted(summary["status_counter"].items(), key=lambda x: -x[1]):
        lines.append(f"    - {status}: {count}")
    lines.append(f"{'=' * 50}")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  Slack posting
# ══════════════════════════════════════════════════════════════════════════════

def send_to_slack(payload: dict) -> bool:
    """POST the message payload to the Slack webhook."""
    if not SLACK_WEBHOOK_URL:
        log.error(
            "SLACK_WEBHOOK_URL is not set!\n"
            "Edit slack_notifier/credentials.py and paste your webhook URL.\n"
            "See README.md for setup instructions."
        )
        return False

    resp = requests.post(
        SLACK_WEBHOOK_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )

    if resp.status_code == 200 and resp.text == "ok":
        log.info("✅ Message sent to Slack successfully!")
        return True
    else:
        log.error(f"❌ Slack webhook failed: {resp.status_code} — {resp.text[:300]}")
        return False


def send_test_ping() -> bool:
    """Send a simple test message to verify the webhook works."""
    payload = {
        "text": f"🏓 *Ping!* Slack webhook is working. (Sent at {datetime.now().strftime('%I:%M %p on %d %B %Y')})"
    }
    return send_to_slack(payload)


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    global WEEKLY_GOAL

    parser = argparse.ArgumentParser(description="Send nightly Slack summary from Notion")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview the message in terminal without sending to Slack")
    parser.add_argument("--test", action="store_true",
                        help="Send a test ping to verify the Slack webhook")
    parser.add_argument("--goal", type=int, default=None,
                        help=f"Override the weekly goal (default: {WEEKLY_GOAL})")
    args = parser.parse_args()

    if args.test:
        success = send_test_ping()
        sys.exit(0 if success else 1)

    # Override weekly goal if provided
    if args.goal is not None:
        WEEKLY_GOAL = args.goal


    # 1. Fetch all pages from Notion
    log.info("Fetching pages from Notion...")
    try:
        pages = fetch_all_pages()
    except Exception as e:
        log.error(f"Failed to fetch from Notion: {e}")
        sys.exit(1)

    # 2. Compute summary
    summary = compute_summary(pages)

    # 3. Format and send/print
    if args.dry_run:
        print(format_plain_text(summary))
        print("\n(--dry-run mode: message was NOT sent to Slack)")
    else:
        payload = format_slack_message(summary)
        success = send_to_slack(payload)
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main()
