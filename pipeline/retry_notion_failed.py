"""
retry_notion_failed.py — Fetch videos with Status='Failed' from Notion,
run sanity checks, and process via the parallel pipeline.

Usage:
    python retry_notion_failed.py [--headless] [--dry-run]
"""
import os, sys, argparse, logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
log_path = os.path.join(
    os.path.dirname(__file__), "logs",
    f"retry_notion_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
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

import requests
from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID,
    PROP_VIDEO_NAME, PROP_AGE_GROUP, PROP_CATEGORY,
    PROP_STATUS, PROP_UPLOAD,
    PROP_FINAL_VIDEO_HINDI_LINK, PROP_FINAL_VIDEO_ENGLISH_LINK,
)
import sanity_checker
import state_manager as sm
from pipeline import run_parallel_pipeline

NOTION_VERSION = "2022-06-28"
BASE = "https://api.notion.com/v1"

def _headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

def _prop_value(properties, name):
    prop = properties.get(name)
    if not prop:
        return ""
    t = prop.get("type", "")
    if t == "title":
        return "".join(p.get("plain_text", "") for p in prop.get("title", [])).strip()
    if t == "rich_text":
        return "".join(p.get("plain_text", "") for p in prop.get("rich_text", [])).strip()
    if t == "select":
        s = prop.get("select")
        return s["name"] if s else ""
    if t == "url":
        return prop.get("url") or ""
    if t == "checkbox":
        return "Yes" if prop.get("checkbox") else "No"
    if t == "multi_select":
        return ", ".join(o["name"] for o in prop.get("multi_select", []))
    return ""


def query_failed_status():
    """Query Notion for pages with Status = 'Failed' (not 'Failed to upload')."""
    url = f"{BASE}/databases/{NOTION_DATABASE_ID}/query"
    results = []
    cursor = None

    while True:
        payload = {
            "filter": {
                "property": PROP_STATUS,
                "select": {"equals": "Failed"},
            },
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for page in data.get("results", []):
            props = page["properties"]
            page_id = page["id"]
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
                    "page_id": page_id,
                    "video_name": tagged_name,
                    "age_group": age_group,
                    "category": category,
                    "drive_link": drive_link,
                    "status": status,
                    "upload": upload,
                    "lang_suffix": lang_suffix,
                })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    log.info(f"\nNotion 'Failed' query: {len(results)} video(s) found.")
    return results


def main():
    parser = argparse.ArgumentParser(description="Retry 'Failed' videos from Notion")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed")
    parser.add_argument("--headless", action="store_true", help="Run Chrome headless")
    parser.add_argument("--skip-upload", action="store_true", help="Stop after zipping")
    args = parser.parse_args()

    log.info(f"\n{'='*60}")
    log.info(f"  Retry 'Failed' Status Videos from Notion")
    log.info(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"  Log: {log_path}")
    log.info(f"{'='*60}")

    # 1. Fetch "Failed" from Notion
    videos = query_failed_status()
    if not videos:
        log.info("No 'Failed' videos found in Notion. Nothing to do.")
        return

    log.info(f"\nFetched {len(videos)} 'Failed' video(s) from Notion:")
    for v in videos:
        log.info(f"  - {v['video_name']} | age={v['age_group']} | cat={v['category']}")

    # 2. Sanity check
    sane_videos, failed_videos = sanity_checker.run(videos, mark_notion=False)

    if failed_videos:
        log.warning(
            f"\n  {len(failed_videos)} video(s) fail sanity check and will be skipped."
        )

    if not sane_videos:
        log.info("\nNo videos passed sanity check. Nothing to process.")
        return

    log.info(f"\n{len(sane_videos)} video(s) passed sanity check.")

    # 2b. Dedup guard: skip content already uploaded in a prior run
    from dedup_utils import normalize_video_key, build_uploaded_keys_from_state
    uploaded_keys = build_uploaded_keys_from_state(sm.get_all())
    deduped = []
    for v in sane_videos:
        key = normalize_video_key(v["video_name"], v.get("age_group", ""))
        if key in uploaded_keys:
            log.warning(
                f"  [DUPE-UPLOAD] Skipping '{v['video_name']}' "
                f"(age={v.get('age_group','?')}) — already uploaded in a prior run"
            )
            continue
        deduped.append(v)
    if len(deduped) < len(sane_videos):
        log.info(f"  Removed {len(sane_videos) - len(deduped)} already-uploaded video(s).")
    sane_videos = deduped

    if not sane_videos:
        log.info("\nAll videos already uploaded. Nothing to process.")
        return

    log.info(f"\n{len(sane_videos)} video(s) entering pipeline.")

    # 3. Reset state for these videos
    for v in sane_videos:
        from dedup_utils import normalize_age as _norm_age
        sm.upsert(
            v["page_id"] + v.get("lang_suffix", ""),
            page_id=v["page_id"],
            video_name=v["video_name"],
            age_group=_norm_age(v["age_group"]),
            category=v["category"],
            drive_link=v["drive_link"],
            lang_suffix=v.get("lang_suffix", ""),
            pipeline_status="pending",
            failure_reason="",
        )

    if args.dry_run:
        log.info("\n-- DRY RUN: would process --")
        for v in sane_videos:
            log.info(f"  {v['video_name']} | {v['age_group']} | {v['category']}")
        log.info("\nDry run complete.")
        return

    # 4. Run parallel pipeline
    run_parallel_pipeline(
        sane_videos,
        headless=args.headless,
        skip_upload=args.skip_upload,
    )

    # 5. Summary
    log.info(f"\n{'='*60}")
    log.info("RETRY 'FAILED' COMPLETE")
    log.info(f"{'='*60}")
    counts = sm.summary()
    for status, n in sorted(counts.items()):
        log.info(f"  {status:20s}: {n}")
    log.info(f"\nLog saved to: {log_path}")


if __name__ == "__main__":
    main()
