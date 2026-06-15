"""
reset_upload_progress.py — Clear Upload Progress for videos in Notion.

Finds all pages where Upload Progress is NOT empty, then clears it.

Usage:
    cd pipeline
    python reset_upload_progress.py           # dry-run (Ready to Upload only)
    python reset_upload_progress.py --apply   # clear (Ready to Upload only)
    python reset_upload_progress.py --all --apply  # clear ALL videos with progress set
"""

import sys
import time
import logging

import notion_client as nc
from config import (
    PROP_STATUS, PROP_UPLOAD_PROGRESS, PROP_VIDEO_NAME,
    STATUS_READY,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def fetch_with_progress(all_statuses=False):
    """Find pages where Upload Progress is NOT empty.
    If all_statuses=True, ignore the Status filter entirely."""
    import requests
    from config import NOTION_TOKEN

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": nc.NOTION_VERSION,
    }

    query_url = nc._query_url()
    results = []
    cursor = None

    while True:
        if all_statuses:
            payload = {
                "filter": {
                    "property": PROP_UPLOAD_PROGRESS, "select": {"is_not_empty": True},
                },
                "page_size": 100,
            }
        else:
            payload = {
                "filter": {
                    "and": [
                        {"property": PROP_STATUS, "select": {"equals": STATUS_READY}},
                        {"property": PROP_UPLOAD_PROGRESS, "select": {"is_not_empty": True}},
                    ]
                },
                "page_size": 100,
            }
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(query_url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for page in data.get("results", []):
            pid = page["id"]
            props = page.get("properties", {})
            video_name = nc._prop_value(props, PROP_VIDEO_NAME)
            progress = nc._prop_value(props, PROP_UPLOAD_PROGRESS)
            status = nc._prop_value(props, PROP_STATUS)
            results.append({"page_id": pid, "video_name": video_name, "progress": progress, "status": status})

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return results


def main():
    apply = "--apply" in sys.argv
    all_statuses = "--all" in sys.argv

    mode = "ALL videos" if all_statuses else "'Ready to Upload' videos only"
    log.info("=" * 60)
    log.info(f"  Reset Upload Progress — {mode}")
    log.info("=" * 60)

    pages = fetch_with_progress(all_statuses=all_statuses)

    if not pages:
        log.info("\n  No pages found with non-empty Upload Progress. All clean!")
        return

    log.info(f"\n  Found {len(pages)} page(s) with Upload Progress set:\n")
    for i, p in enumerate(pages, 1):
        log.info(f"  {i:3d}. [{p['progress']:>12s}] [{p['status']:>18s}]  {p['video_name']}")

    if not apply:
        log.info(f"\n  DRY RUN — no changes made.")
        log.info(f"  Run with --apply to clear Upload Progress for these {len(pages)} pages.")
        return

    log.info(f"\n  Clearing Upload Progress for {len(pages)} pages...\n")
    ok = 0
    fail = 0
    for i, p in enumerate(pages, 1):
        success = nc.clear_upload_progress_in_notion(p["page_id"])
        if success:
            ok += 1
            log.info(f"  [{i}/{len(pages)}] OK  {p['video_name']}")
        else:
            fail += 1
            log.info(f"  [{i}/{len(pages)}] FAIL  {p['video_name']}")
        time.sleep(0.35)  # Notion rate limit

    log.info(f"\n  Done: {ok} cleared, {fail} failed.")


if __name__ == "__main__":
    main()

