#!/usr/bin/env python3
"""
update_video_age_groups.py
===========================
Automates updating the age groups of specified videos in the CMS Video Library.

Features:
- Search video by Video ID in the CMS Video Library using React Native Value Setter.
- Open video Edit modal.
- Select/toggle appropriate Age Groups ("0-3", "3-6", "6+").
- Click "Save Changes" to save changes in CMS.
- Accepts input via CSV file, JSON file, CLI arguments, or interactive input.
- Real-time incremental reporting and status logging.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from typing import List, Dict, Any, Set, Tuple

# ── Add pipeline/ directory to path ───────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(BASE_DIR, "pipeline")
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import config as cfg
import uploader

VIDEO_LIBRARY_URL = f"{cfg.ADMIN_BASE_URL}/dashboard/cms/video-library"
VALID_AGE_GROUPS = {"0-3", "3-6", "6+"}


def normalize_age_groups(raw_groups: Any) -> List[str]:
    if isinstance(raw_groups, str):
        if raw_groups.strip().lower() in ["all", "all 3", "all three", "0-3, 3-6, 6+"]:
            return ["0-3", "3-6", "6+"]
        raw_items = [item.strip() for item in raw_groups.replace("/", ",").split(",")]
    elif isinstance(raw_groups, (list, tuple, set)):
        raw_items = [str(item).strip() for item in raw_groups]
    else:
        raw_items = []

    normalized = set()
    for item in raw_items:
        clean = item.lower()
        if clean in ["all", "all 3", "all three"]:
            return ["0-3", "3-6", "6+"]
        elif clean in ["0-3", "0-3 age group", "0 - 3", "under 3", "under 3 age", "0-3 years"]:
            normalized.add("0-3")
        elif clean in ["3-6", "3-6 age group", "3 - 6", "3 to 6", "3-6 years"]:
            normalized.add("3-6")
        elif clean in ["6+", "6+ age group", "6 plus", "above 6", "6+ years"]:
            normalized.add("6+")
        else:
            if "0" in clean and "3" in clean and "6" not in clean:
                normalized.add("0-3")
            elif "3" in clean and "6" in clean:
                normalized.add("3-6")
            elif "6" in clean:
                normalized.add("6+")

    return sorted(list(normalized))


def parse_input_file(csv_path: str = "", json_path: str = "") -> List[Dict[str, Any]]:
    items = []
    if csv_path and os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                vid = row.get("video_id") or row.get("id") or row.get("CMS Video ID") or row.get("video_name")
                ag = row.get("age_groups") or row.get("age_group") or row.get("Age Group") or row.get("age")
                if vid and ag:
                    items.append({
                        "video_id": vid.strip(),
                        "age_groups": normalize_age_groups(ag)
                    })

    elif json_path and os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                for entry in data:
                    vid = entry.get("video_id") or entry.get("id")
                    ag = entry.get("age_groups") or entry.get("age_group")
                    if vid and ag:
                        items.append({
                            "video_id": str(vid).strip(),
                            "age_groups": normalize_age_groups(ag)
                        })
            elif isinstance(data, dict):
                for vid, ag in data.items():
                    items.append({
                        "video_id": str(vid).strip(),
                        "age_groups": normalize_age_groups(ag)
                    })

    return items


def update_single_video_age_groups(driver, video_id: str, target_age_groups: List[str]) -> Tuple[bool, str]:
    try:
        if "/dashboard/cms/video-library" not in driver.current_url:
            driver.get(VIDEO_LIBRARY_URL)
            time.sleep(2.5)

        # Close any open modals
        driver.execute_script("""
            const cancels = document.querySelectorAll('.btn-cancel, [aria-label="Close"]');
            cancels.forEach(c => c.click());
        """)
        time.sleep(0.5)

        # Search video ID in input tab using React Native Value Setter
        search_inputs = driver.find_elements("css selector", "input.cms-filter-search, input[placeholder*='Search']")
        if not search_inputs:
            driver.get(VIDEO_LIBRARY_URL)
            time.sleep(2.5)
            search_inputs = driver.find_elements("css selector", "input.cms-filter-search, input[placeholder*='Search']")
            if not search_inputs:
                return False, "Search input field not found"

        search_inp = search_inputs[0]

        # Use React Native Setter to ensure React state updates and filters table
        driver.execute_script("""
            const el = arguments[0];
            const val = arguments[1];
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            nativeInputValueSetter.call(el, val);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """, search_inp, video_id)
        time.sleep(2.0)

        # Find matching edit button
        edit_btn = None
        rows = driver.find_elements("css selector", "table tbody tr")

        for row in rows:
            row_text = row.text.strip()
            if video_id.lower() in row_text.lower() or len(rows) == 1:
                buttons = row.find_elements("css selector", "button")
                for btn in buttons:
                    if btn.text.strip().lower() == "edit":
                        edit_btn = btn
                        break
            if edit_btn:
                break

        if not edit_btn:
            return False, f"Video ID '{video_id}' not found in search results"

        driver.execute_script("arguments[0].click();", edit_btn)
        time.sleep(2.0)

        modal_elements = driver.find_elements("css selector", ".bab-ref-edit-root.modal, [role='dialog'], .cu-modal-overlay")
        if not modal_elements:
            return False, "Edit modal did not open"

        modal = modal_elements[0]
        target_set = set(target_age_groups)

        chip_buttons = modal.find_elements("css selector", ".chip-opt, button")
        age_chips = [c for c in chip_buttons if c.text.strip() in VALID_AGE_GROUPS]

        if not age_chips:
            return False, "Age group option chips not found in modal"

        for chip in age_chips:
            label = chip.text.strip()
            is_selected = "sel" in chip.get_attribute("class")
            should_be_selected = label in target_set

            if is_selected != should_be_selected:
                driver.execute_script("arguments[0].click();", chip)
                time.sleep(0.3)

        save_btn = None
        for b in modal.find_elements("css selector", "button"):
            if "save changes" in b.text.strip().lower() or "save" in b.text.strip().lower():
                save_btn = b
                break

        if not save_btn:
            return False, "'Save Changes' button not found"

        driver.execute_script("arguments[0].click();", save_btn)
        time.sleep(2.5)

        return True, "Successfully updated age groups in CMS"

    except Exception as e:
        return False, f"Exception: {str(e)}"


def run_batch_update(video_items: List[Dict[str, Any]], headless: bool = False) -> List[Dict[str, Any]]:
    if not video_items:
        print("❌ No valid video items provided.", flush=True)
        return []

    report_file = os.path.join(BASE_DIR, "update_age_groups_summary.json")

    print(f"\n==================================================", flush=True)
    print(f"  Starting Age Group Update Pipeline ({len(video_items)} videos)", flush=True)
    print(f"==================================================\n", flush=True)

    print("🌐 Launching browser driver...", flush=True)
    driver = uploader.build_driver(headless=headless)
    results = []

    try:
        print("🔐 Logging into CMS Dashboard...", flush=True)
        if not uploader.login(driver):
            print("❌ Login failed. Check credentials.", flush=True)
            return []

        print("✅ Logged in successfully!\n", flush=True)

        for idx, item in enumerate(video_items, 1):
            vid = item["video_id"]
            target_ag = item["age_groups"]
            print(f"[{idx}/{len(video_items)}] Processing Video ID: {vid}", flush=True)
            print(f"  -> Target Age Groups: {target_ag}", flush=True)

            success, msg = update_single_video_age_groups(driver, vid, target_ag)
            status_str = "SUCCESS" if success else "FAILED"
            icon = "✅" if success else "❌"

            print(f"  -> Result: {icon} {status_str} ({msg})\n", flush=True)

            res = {
                "index": idx,
                "total": len(video_items),
                "video_id": vid,
                "target_age_groups": target_ag,
                "success": success,
                "status": status_str,
                "message": msg,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            results.append(res)

            # Save incremental summary report
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)

    finally:
        print("🔒 Closing browser...", flush=True)
        driver.quit()

    print("\n==================================================", flush=True)
    print("  SUMMARY REPORT", flush=True)
    print("==================================================", flush=True)
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    print(f"Total Videos Processed : {len(results)}", flush=True)
    print(f"Successfully Updated   : {success_count}", flush=True)
    print(f"Failed Updates         : {fail_count}", flush=True)
    print(f"Detailed Summary saved : {report_file}", flush=True)
    print("==================================================\n", flush=True)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Automate age group updates for CMS videos in Video Library"
    )
    parser.add_argument("--csv", "-c", type=str, default="", help="Path to input CSV file")
    parser.add_argument("--json", "-j", type=str, default="", help="Path to input JSON file")
    parser.add_argument("--video-id", "-v", type=str, default="", help="Single Video ID to update")
    parser.add_argument(
        "--age-groups", "-a", nargs="+", default=[], help="Target age groups"
    )
    parser.add_argument(
        "--headless", action="store_true", help="Run Chrome browser in headless mode"
    )

    args = parser.parse_args()
    video_items = []

    if args.csv or args.json:
        video_items = parse_input_file(csv_path=args.csv, json_path=args.json)
    elif args.video_id and args.age_groups:
        video_items = [{
            "video_id": args.video_id.strip(),
            "age_groups": normalize_age_groups(args.age_groups)
        }]

    if not video_items:
        sys.exit(1)

    run_batch_update(video_items, headless=args.headless)


if __name__ == "__main__":
    main()
