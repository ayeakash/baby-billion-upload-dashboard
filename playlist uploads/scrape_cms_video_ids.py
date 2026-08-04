"""
scrape_cms_video_ids.py
========================
Scrapes the CMS Video Library to build a mapping of video_title → CMS video_id.
Then cross-references with Characters.csv to generate correct top-10 CSVs
with valid CMS video_ids.

Usage:
    python scrape_cms_video_ids.py
"""
import csv, json, os, re, sys, time
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "pipeline"))

import config as cfg
import uploader

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "cms_video_id_map.json"

CMS_VIDEO_LIBRARY_URL = f"{cfg.ADMIN_BASE_URL}/dashboard/cms/video-library"


def scrape_video_library(driver, By, EC):
    """Scrape all videos from the CMS Video Library and return {title: video_id}."""
    print("  Navigating to Video Library...")
    driver.get(CMS_VIDEO_LIBRARY_URL)
    time.sleep(5)

    video_map = {}  # title -> video_id
    page = 1

    while True:
        print(f"  Scraping page {page}...", end="", flush=True)

        # Get all video entries from the table/list
        videos_on_page = driver.execute_script("""
        return (() => {
            const results = [];
            // Try table rows
            const rows = document.querySelectorAll('table tbody tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 2) {
                    // Typically: video_id, title, ...
                    const id = cells[0]?.innerText?.trim() || '';
                    const title = cells[1]?.innerText?.trim() || '';
                    if (id && /^[0-9a-f]{8}-/.test(id)) {
                        results.push({id: id, title: title});
                    }
                }
            }
            // Try list items if no table
            if (results.length === 0) {
                const items = document.querySelectorAll('[class*="video"], [class*="item"], [class*="card"]');
                for (const item of items) {
                    const text = item.innerText || '';
                    const match = text.match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
                    if (match) {
                        // Try to find a title nearby
                        const lines = text.split('\\n').map(l => l.trim()).filter(l => l);
                        const title = lines.find(l => !l.match(/^[0-9a-f]{8}-/) && l.length > 2) || '';
                        results.push({id: match[1], title: title});
                    }
                }
            }
            return results;
        })();
        """)

        if not videos_on_page:
            print(f" no videos found on page")
            # Dump page text for debugging
            body_text = driver.execute_script("return document.body.innerText.substring(0, 2000)")
            print(f"  Page text preview:\n{body_text[:500]}")
            break

        for v in videos_on_page:
            vid = v.get("id", "").strip()
            title = v.get("title", "").strip()
            if vid and title:
                video_map[title] = vid

        print(f" found {len(videos_on_page)} videos (total: {len(video_map)})")

        # Try to click Next page
        next_clicked = driver.execute_script("""
        return (() => {
            // Look for next/pagination buttons
            const btns = document.querySelectorAll('button, a');
            for (const btn of btns) {
                const text = btn.innerText?.trim()?.toLowerCase() || '';
                const ariaLabel = btn.getAttribute('aria-label')?.toLowerCase() || '';
                if (text === 'next' || text === '>' || text === '→' || 
                    ariaLabel.includes('next') || text === '»') {
                    if (!btn.disabled) {
                        btn.click();
                        return true;
                    }
                }
            }
            // Also try numbered pagination
            const current = document.querySelector('[class*="active"] [class*="page"], .active.page-item');
            if (current) {
                const next = current.nextElementSibling;
                if (next) {
                    const link = next.querySelector('a, button');
                    if (link) { link.click(); return true; }
                }
            }
            return false;
        })();
        """)

        if not next_clicked:
            print("  No more pages.")
            break

        page += 1
        time.sleep(3)

    return video_map


def main():
    _, _, _, By, _, EC, *_ = uploader._get_selenium()

    print("=" * 60)
    print("  CMS Video Library Scraper")
    print("=" * 60)

    driver = uploader.build_driver(headless=False)

    try:
        if not uploader.login(driver):
            print("  Login failed!")
            return

        video_map = scrape_video_library(driver, By, EC)

        # Save the mapping
        with OUTPUT_FILE.open("w", encoding="utf-8") as f:
            json.dump(video_map, f, indent=2)

        print(f"\n  Saved {len(video_map)} video mappings to {OUTPUT_FILE}")

    finally:
        input("\n  Press Enter to close browser...")
        driver.quit()


if __name__ == "__main__":
    main()
