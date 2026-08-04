"""
check_cms_duplicates.py — Scrape CMS Upload History and check for duplicate (video_name, category) uploads.
"""

import os
import sys
import re
import json
import time
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(BASE_DIR, "pipeline")
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import uploader
import config as cfg

from selenium.webdriver.common.by import By

UPLOAD_HISTORY_URL = f"{cfg.ADMIN_BASE_URL}/dashboard/cms/content-upload"

TARGET_JOB_IDS = {
    "Batch_05": "2ba466c3-1c6c-42b1-b3b2-b13e4634ad14",
    "Batch_06": "e08b7ed9-f113-4bf9-b5f2-426b7f20cec9",
    "Batch_07": "44ff0b04-67d2-4d95-b01e-d8a0e5012d18",
    "Batch_08": "c0b16079-e048-4b71-b8fc-9849c0c27546",
    "Batch_09": "1309eced-94c8-4616-a988-8f16a25a1fce",
}


def main():
    driver = uploader.build_driver(headless=True)
    try:
        print("Logging into CMS...")
        if not uploader.login(driver):
            print("Login failed!")
            return

        print("Navigating to Video Upload page...")
        driver.get(UPLOAD_HISTORY_URL)
        time.sleep(3)

        # Click on 'Upload History' tab
        for el in driver.find_elements(By.CSS_SELECTOR, "button, a, span, div"):
            if el.text and "upload history" in el.text.strip().lower():
                try:
                    driver.execute_script("arguments[0].click();", el)
                    print("Clicked 'Upload History' tab.")
                    time.sleep(3)
                    break
                except Exception:
                    pass

        # Scrape all history rows in the table
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        print(f"Found {len(rows)} rows in Upload History table.\n")

        history_entries = []
        for r in rows:
            cells = r.find_elements(uploader.By.CSS_SELECTOR, "td")
            if len(cells) >= 5:
                row_text = r.text.strip()
                history_entries.append((row_text, r))

        # Check each target Job ID
        scraped_videos = []  # list of dicts {batch_name, job_id, video_name, category, age, channel, language}

        for bname, target_job_id in TARGET_JOB_IDS.items():
            print(f"\n============================================================")
            print(f"  Checking {bname} (Job ID: {target_job_id})")
            print(f"============================================================")

            # Re-navigate to Upload History tab
            driver.get(UPLOAD_HISTORY_URL)
            time.sleep(2)
            for el in driver.find_elements(By.CSS_SELECTOR, "button, a, span, div"):
                if el.text and "upload history" in el.text.strip().lower():
                    try:
                        driver.execute_script("arguments[0].click();", el)
                        time.sleep(2)
                        break
                    except Exception:
                        pass

            # Find matching row in history table
            found_row = None
            for r in driver.find_elements(By.CSS_SELECTOR, "table tbody tr"):
                if target_job_id in r.text or (len(target_job_id) > 8 and target_job_id[:8] in r.text):
                    found_row = r
                    break

            if not found_row:
                print(f"  ⚠️ Could not find history row for Job ID: {target_job_id}")
                continue

            # Look for "View" or "Details" button in the row
            view_btn = None
            for btn in found_row.find_elements(By.CSS_SELECTOR, "button, a"):
                txt = btn.text.strip().lower()
                if "view" in txt or "detail" in txt or "inspect" in txt:
                    view_btn = btn
                    break

            if view_btn:
                driver.execute_script("arguments[0].click();", view_btn)
                time.sleep(3)
            else:
                # Try clicking cell
                cells = found_row.find_elements(By.CSS_SELECTOR, "td")
                if cells:
                    driver.execute_script("arguments[0].click();", cells[0])
                    time.sleep(3)

            # Extract video rows from the detail page
            v_rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            if not v_rows:
                # Parse body text
                body_text = driver.execute_script("return document.body.innerText || ''")
                print(f"  Snippet: {body_text[:300]}")
            else:
                print(f"  Found {len(v_rows)} videos in batch detail view:")
                for vr in v_rows:
                    v_cells = vr.find_elements(By.CSS_SELECTOR, "td")
                    if len(v_cells) >= 3:
                        # Extract title, category, age, channel, language
                        c_texts = [c.text.strip() for c in v_cells if c.text.strip()]
                        # Format is usually: [Video UUID, Video Title, Category, Age Bracket, Channel, Language]
                        title = ""
                        cat = ""
                        age = ""
                        channel = ""
                        lang = ""

                        if len(c_texts) >= 2:
                            # UUID might be c_texts[0], title c_texts[1]
                            if re.match(r'[0-9a-f]{8}-', c_texts[0], re.I):
                                title = c_texts[1] if len(c_texts) > 1 else ""
                                cat = c_texts[2] if len(c_texts) > 2 else ""
                                age = c_texts[3] if len(c_texts) > 3 else ""
                                channel = c_texts[4] if len(c_texts) > 4 else ""
                                lang = c_texts[5] if len(c_texts) > 5 else ""
                            else:
                                title = c_texts[0]
                                cat = c_texts[1] if len(c_texts) > 1 else ""
                                age = c_texts[2] if len(c_texts) > 2 else ""

                        if title:
                            print(f"    - {title} | Cat: '{cat}' | Age: '{age}' | Channel: '{channel}' | Lang: '{lang}'")
                            scraped_videos.append({
                                "batch": bname,
                                "job_id": target_job_id,
                                "video_name": title,
                                "category": cat,
                                "age_group": age,
                                "channel": channel,
                                "language": lang
                            })

        # Save scraped verification result
        out_path = os.path.join(BASE_DIR, "cms_upload_verification.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(scraped_videos, f, indent=2, ensure_ascii=False)

        # Check for duplicates: (video_name, category)
        print(f"\n============================================================")
        print(f"  DUPLICATE CHECK RESULTS")
        print(f"============================================================")
        print(f"  Total uploaded videos checked: {len(scraped_videos)}")

        seen_pairs = defaultdict(list)
        for item in scraped_videos:
            v_norm = re.sub(r'_+', '_', re.sub(r'[^\w]', '_', item["video_name"].lower())).strip('_')
            c_norm = item["category"].strip().lower()
            key = (v_norm, c_norm)
            seen_pairs[key].append(item)

        duplicates_found = 0
        for (v_norm, c_norm), items in seen_pairs.items():
            if len(items) > 1:
                duplicates_found += 1
                orig_title = items[0]["video_name"]
                orig_cat = items[0]["category"]
                print(f"  ⚠️ DUPLICATE FOUND: Video '{orig_title}' in Category '{orig_cat}' appears {len(items)} times!")
                for it in items:
                    print(f"      -> Batch: {it['batch']} | Job ID: {it['job_id']}")

        if duplicates_found == 0:
            print("  ✅ NO DUPLICATES FOUND! All videos in these batches are unique within their respective categories.")

        print("============================================================\n")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
