"""
retry_failed_notion.py — Fetch "Failed to upload" videos from Notion,
run them through sanity check (with auto-fixes), and process via the
parallel pipeline.

Usage:
    python retry_failed_notion.py [--dry-run] [--headless] [--skip-upload]
"""

import os
import sys
import argparse
import logging
from datetime import datetime

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
log_path = os.path.join(
    os.path.dirname(__file__), "logs",
    f"retry_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
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

import notion_client as nc
import sanity_checker
import state_manager as sm
from pipeline import run_parallel_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Retry 'Failed to upload' videos from Notion"
    )
    parser.add_argument("--dry-run",     action="store_true", help="Show what would be processed")
    parser.add_argument("--headless",    action="store_true", help="Run Chrome headless")
    parser.add_argument("--skip-upload", action="store_true", help="Stop after zipping")
    args = parser.parse_args()

    log.info(f"\n{'='*60}")
    log.info(f"  Retry Failed-to-Upload Videos")
    log.info(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"  Log: {log_path}")
    log.info(f"{'='*60}")

    # ── 1. Fetch "Failed to upload" from Notion ──────────────────────────────
    if not nc.validate_connection():
        sys.exit(1)

    videos = nc.query_failed_to_upload()
    if not videos:
        log.info("No 'Failed to upload' videos found in Notion. Nothing to do.")
        return

    log.info(f"\nFetched {len(videos)} 'Failed to upload' video(s) from Notion:")
    for v in videos:
        log.info(f"  • {v['video_name']} | age={v['age_group']} | cat={v['category']}")

    # ── 2. Sanity check (with auto-fixes for casing + safety override) ───────
    sane_videos, failed_videos = sanity_checker.run(videos, mark_notion=True)

    if failed_videos:
        log.warning(
            f"\n  {len(failed_videos)} video(s) STILL fail sanity check "
            f"and remain marked 'Failed to upload' in Notion."
        )

    if not sane_videos:
        log.info("\nNo videos passed sanity check. Nothing to process.")
        return

    log.info(f"\n{len(sane_videos)} video(s) passed sanity check.")

    # ── 2b. Dedup guard: skip content already uploaded in a prior run ────────
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

    # ── 3. Reset state for these videos so they can be re-processed ──────────
    for v in sane_videos:
        # Reset status in Notion back to "Ready to Upload" so the pipeline
        # can track them properly after upload
        from dedup_utils import normalize_age as _norm_age
        sm.upsert(
            v["page_id"],
            video_name=v["video_name"],
            age_group=_norm_age(v["age_group"]),
            category=v["category"],
            drive_link=v["drive_link"],
            pipeline_status="pending",
            failure_reason="",     # clear old failure
        )

    if args.dry_run:
        log.info("\n-- DRY RUN: would process --")
        for v in sane_videos:
            log.info(f"  {v['video_name']} | {v['age_group']} | {v['category']} | {v['drive_link'][:60]}")
        log.info("\nDry run complete. No downloads or uploads performed.")
        return

    # ── 4. Run parallel pipeline ─────────────────────────────────────────────
    batch_job_map = run_parallel_pipeline(
        sane_videos,
        headless=args.headless,
        skip_upload=args.skip_upload,
    )

    # ── 5. Summary ────────────────────────────────────────────────────────────
    log.info(f"\n{'='*60}")
    log.info("RETRY COMPLETE")
    log.info(f"{'='*60}")
    counts = sm.summary()
    for status, n in sorted(counts.items()):
        log.info(f"  {status:20s}: {n}")
    log.info(f"\nLog saved to: {log_path}")


if __name__ == "__main__":
    main()
