"""
playlist_csv_uploader.py
========================
Automates uploading playlist top-10 CSV files to BabyBillion dashboard categories.

For each CSV file:
  1. Find the matching category on the dashboard
  2. Click Edit
  3. Set status to Active (if currently Inactive)
  4. Upload the CSV via the hidden file input
  5. Save Changes

Usage:
    python playlist_csv_uploader.py             # full run
    python playlist_csv_uploader.py --dry-run   # just show the plan
"""

import os
import sys
import csv
import time
import json
import logging
import argparse
import re
from pathlib import Path

# ── Add pipeline dir to path so we can reuse their Selenium setup ─────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent  # upload_dashboard/
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

try:
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    ChromeDriverManager = None

# ===== Configuration =====

CSV_DIR = SCRIPT_DIR / "BabyBillion_Playlist_TopVideos"
LOG_FILE = SCRIPT_DIR / "playlist_upload_log.txt"

BASE_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com"
LOGIN_URL = f"{BASE_URL}/login"
CATEGORIES_URL = f"{BASE_URL}/dashboard/cms/categories"
# Credentials come from pipeline/credentials.py (gitignored) or env vars.
# NEVER hardcode them here — this file is committed to a public repo.
sys.path.insert(0, str(SCRIPT_DIR.parent / "pipeline"))
try:
    from config import BB_USERNAME as USERNAME, BB_PASSWORD as PASSWORD
except ImportError:
    USERNAME = os.environ.get("BB_USERNAME", "")
    PASSWORD = os.environ.get("BB_PASSWORD", "")
if not USERNAME or not PASSWORD:
    raise SystemExit("Set BB_USERNAME/BB_PASSWORD in pipeline/credentials.py or env vars.")

# CSV filename stem -> exact dashboard category name
# (only for names that DON'T match after simple underscore->space conversion)
NAME_MAP = {
    "Odd_Even":         "Odd & Even",
    "Sounds_Words":     "Sounds & Words",
    "Art_Craft":        "Art & Craft",
    "Let_s_Go_Outside": "Let's Go Outside",
    "100_200":          "100-200",
    "1_100":            "1-100",
}

# Stems to skip (no dashboard match or known duplicates)
SKIP_PREFIXES = set()

# Detect hex-hash suffixed duplicates, e.g. Place_Your_Numbers_98263b2e
HEX_SUFFIX_RE = re.compile(r"_[0-9a-f]{8}$")

# ===== Logging =====

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
    ],
)
log = logging.getLogger("playlist_uploader")

# ===== Helpers =====

def prefix_to_category_name(prefix):
    if prefix in NAME_MAP:
        return NAME_MAP[prefix]
    name = prefix.replace("___", " & ")
    name = name.replace("_", " ")
    return name


def count_data_rows(filepath):
    with filepath.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            next(reader)
        except StopIteration:
            return 0
        return sum(1 for row in reader if any(cell.strip() for cell in row))


def build_upload_plan():
    plan = []
    seen_cats = set()  # avoid uploading to the same category twice

    for f in sorted(CSV_DIR.iterdir()):
        if f.suffix != ".csv":
            continue

        stem = f.stem

        # Strip hex-hash suffix from duplicates (e.g. _98263b2e)
        base = HEX_SUFFIX_RE.sub("", stem)

        if base in SKIP_PREFIXES:
            log.info(f"  SKIP {f.name} (in skip list)")
            continue

        cat = prefix_to_category_name(base)

        if cat in seen_cats:
            log.info(f"  SKIP {f.name} (duplicate for '{cat}')")
            continue

        rows = count_data_rows(f)
        plan.append({
            "file": f, "name": f.name,
            "rows": rows, "cat": cat,
        })
        seen_cats.add(cat)

        marker = "[OK]" if rows == 10 else "[!!]"
        log.info(f"  {marker} {cat:35s} <- {f.name:45s} ({rows:2d} rows)")

    log.info(f"\n{'=' * 70}")
    log.info(f"  Total categories to process: {len(plan)}")
    log.info(f"{'=' * 70}\n")
    return plan

# ===== Selenium - Driver & Login =====

def make_driver():
    opts = Options()
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    if ChromeDriverManager:
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)
    return webdriver.Chrome(options=opts)


def do_login(driver):
    log.info("Navigating to login page...")
    driver.get(LOGIN_URL)
    time.sleep(3)

    if "/login" not in driver.current_url:
        log.info("Already logged in (redirected).")
        return True

    try:
        wait = WebDriverWait(driver, 15)
        email = wait.until(EC.presence_of_element_located((
            By.CSS_SELECTOR,
            "input[type='text'], input[type='email'], input[name='username'], input[name='email']"
        )))
        email.clear()
        email.send_keys(USERNAME)

        pw = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        pw.clear()
        pw.send_keys(PASSWORD)

        btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        btn.click()
        log.info("Login button clicked -- waiting for redirect...")

        for _ in range(15):
            time.sleep(1)
            if "/login" not in driver.current_url:
                log.info("Login successful!")
                return True

        log.error("Login failed -- still on login page.")
        return False
    except Exception as e:
        log.error(f"Login error: {e}")
        return False

# ===== JavaScript Snippets =====

# Finds a category by name, scrolls to it, clicks its Edit button via JS
JS_FIND_AND_CLICK_EDIT = """
return (function(targetName) {
    var items = document.querySelectorAll('.cms-list-item');
    for (var i = 0; i < items.length; i++) {
        var nameEl = items[i].querySelector('.cms-item-name');
        if (!nameEl) continue;

        // Clone and remove status tags to get pure category name
        var clone = nameEl.cloneNode(true);
        var tags = clone.querySelectorAll('.tag');
        for (var t = 0; t < tags.length; t++) { tags[t].remove(); }
        var name = clone.textContent.trim();

        if (name === targetName) {
            var actionsDiv = items[i].querySelector('.cms-item-actions');
            if (actionsDiv) {
                var editBtn = actionsDiv.querySelector('button');
                if (editBtn) {
                    editBtn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    editBtn.click();
                    return 'clicked_' + i;
                }
            }
        }
    }
    return 'not_found';
})(arguments[0]);
"""

# Click Active button in edit modal if currently Inactive
JS_CLICK_ACTIVE = """
return (function() {
    var modal = document.querySelector('.bab-ref-edit-root, .modal-lg');
    if (!modal) return 'no_modal';

    var buttons = modal.querySelectorAll('button');
    var activeBtn = null;
    var isAlreadyActive = false;

    for (var i = 0; i < buttons.length; i++) {
        var text = buttons[i].textContent.trim();
        if (text === 'Active') {
            activeBtn = buttons[i];
            if (buttons[i].classList.contains('sel')) {
                isAlreadyActive = true;
            }
        }
    }

    if (isAlreadyActive) return 'already_active';

    if (activeBtn) {
        activeBtn.click();
        return 'activated';
    }

    return 'no_active_button';
})();
"""

# Unhide the CSV file input and return it as a WebElement
JS_UNHIDE_FILE_INPUT = """
return (function() {
    var inp = document.querySelector('input[type="file"][accept=".csv,text/csv"]');
    if (!inp) {
        // Fallback: any file input
        var all = document.querySelectorAll('input[type="file"]');
        for (var i = 0; i < all.length; i++) {
            if ((all[i].getAttribute('accept') || '').indexOf('csv') !== -1) {
                inp = all[i];
                break;
            }
        }
    }
    if (inp) {
        inp.style.display = 'block';
        inp.style.visibility = 'visible';
        inp.style.height = '1px';
        inp.style.width = '1px';
        inp.style.opacity = '0.01';
        inp.style.position = 'absolute';
        inp.style.zIndex = '99999';
        inp.removeAttribute('hidden');
        return inp;
    }
    return null;
})();
"""

# ===== Category Operations =====

def go_to_categories(driver):
    driver.get(CATEGORIES_URL)
    time.sleep(4)
    if "/login" in driver.current_url:
        log.warning("Session expired -- re-logging in...")
        if not do_login(driver):
            raise RuntimeError("Re-login failed")
        driver.get(CATEGORIES_URL)
        time.sleep(4)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".cms-list-item"))
        )
    except TimeoutException:
        log.warning("Timeout waiting for .cms-list-item")
    log.info("Categories page loaded.")


def find_and_click_edit(driver, category_name):
    """Find category by name and click Edit -- returns True if clicked."""
    result = driver.execute_script(JS_FIND_AND_CLICK_EDIT, category_name)
    if result and result.startswith("clicked"):
        time.sleep(1)
        return True
    return False


def wait_for_modal(driver, timeout=10):
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".bab-ref-edit-root, .modal-lg"))
        )
        time.sleep(1)
        return True
    except TimeoutException:
        return False


def set_active(driver):
    result = driver.execute_script(JS_CLICK_ACTIVE)
    if result == 'activated':
        log.info("    -> Set status to Active")
        time.sleep(0.5)
    elif result == 'already_active':
        log.info("    -> Already Active")
    else:
        log.warning(f"    -> Active status: {result}")
    return result


def upload_csv(driver, filepath):
    """Upload CSV via hidden file input."""
    file_input = driver.execute_script(JS_UNHIDE_FILE_INPUT)
    if not file_input:
        log.error("    [FAIL] No CSV file input found!")
        return False
    try:
        file_input.send_keys(str(filepath.resolve()))
        time.sleep(3)
        log.info(f"    -> CSV uploaded: {filepath.name}")
        return True
    except Exception as e:
        log.error(f"    [FAIL] send_keys failed: {e}")
        return False


def check_for_rejection(driver):
    """Check if the dashboard rejected the CSV upload."""
    result = driver.execute_script(
        'var modal = document.querySelector(".bab-ref-edit-root, .modal-lg");'
        'if (!modal) return "ok";'
        'var text = modal.innerText || "";'
        'var idx = text.indexOf("Rejected");'
        'if (idx !== -1) { return text.substring(idx, idx + 200); }'
        'return "ok";'
    )
    if result and result != "ok":
        log.error(f"    [REJECTED] {result.split(chr(10))[0]}")
        return True
    return False


def save_changes(driver):
    try:
        btns = driver.find_elements(By.CSS_SELECTOR, "button")
        for btn in btns:
            txt = btn.text.strip()
            if "Save" in txt and "Change" in txt:
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(3)
                log.info("    -> Save Changes clicked")
                return True
        # Fallback
        for btn in btns:
            if "save" in btn.text.strip().lower():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(3)
                log.info("    -> Save clicked (fallback)")
                return True
        log.error("    [FAIL] Save button not found!")
        return False
    except Exception as e:
        log.error(f"    [FAIL] Save error: {e}")
        return False


def close_modal(driver):
    try:
        btns = driver.find_elements(By.CSS_SELECTOR, "button")
        for btn in btns:
            if btn.text.strip() == "Cancel":
                btn.click()
                time.sleep(1)
                return
        from selenium.webdriver.common.keys import Keys
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(1)
    except Exception:
        pass


def wait_for_modal_close(driver, timeout=10):
    try:
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, ".bab-ref-edit-root, .modal-lg"))
        )
        time.sleep(1)
    except TimeoutException:
        log.warning("    Modal didn't close in time -- continuing")

# ===== Main =====

def main():
    parser = argparse.ArgumentParser(description="Upload playlist CSVs to BabyBillion categories")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without uploading")
    parser.add_argument("--start-from", type=int, default=0, help="Start from index (0-based)")
    args = parser.parse_args()

    log.info("=" * 70)
    log.info("  BabyBillion Playlist CSV Uploader")
    log.info("=" * 70)
    log.info(f"  CSV directory: {CSV_DIR}")
    log.info(f"  Dashboard:     {CATEGORIES_URL}\n")

    plan = build_upload_plan()

    if args.dry_run:
        log.info("Dry run complete. No uploads performed.")
        return

    if args.start_from > 0:
        plan = plan[args.start_from:]
        log.info(f"Resuming from index {args.start_from}, {len(plan)} remaining.\n")

    driver = make_driver()
    results = {"success": [], "failed": [], "skipped": []}

    try:
        if not do_login(driver):
            log.error("Cannot proceed -- login failed.")
            return

        go_to_categories(driver)
        processed_cats = set()

        for i, item in enumerate(plan):
            cat = item["cat"]
            csv_file = item["file"]
            idx = args.start_from + i

            log.info(f"\n{'=' * 70}")
            log.info(f"  [{idx + 1}/{args.start_from + len(plan)}]  {cat}")
            log.info(f"  CSV: {item['name']}  ({item['rows']} rows)")
            log.info(f"{'=' * 70}")

            if cat in processed_cats:
                log.info(f"    SKIP: Already processed '{cat}'")
                results["skipped"].append(item)
                continue

            # Step 1: Find and click Edit
            if not find_and_click_edit(driver, cat):
                log.warning(f"    SKIP: Category '{cat}' not found on dashboard")
                results["skipped"].append(item)
                continue

            # Step 2: Wait for edit modal
            if not wait_for_modal(driver):
                log.error(f"    FAIL: Edit modal did not open for '{cat}'")
                results["failed"].append(item)
                continue

            # Step 3: Set Active
            set_active(driver)

            # Step 4: Upload CSV
            if not upload_csv(driver, csv_file):
                log.error(f"    FAIL: CSV upload failed for '{cat}'")
                close_modal(driver)
                time.sleep(1)
                results["failed"].append(item)
                continue

            # Step 5: Check for rejection
            if check_for_rejection(driver):
                log.error(f"    FAIL: CSV rejected for '{cat}'")
                close_modal(driver)
                time.sleep(1)
                results["failed"].append(item)
                continue

            # Step 6: Save
            if save_changes(driver):
                wait_for_modal_close(driver)
                results["success"].append(item)
                processed_cats.add(cat)
                log.info(f"    DONE: {cat}")
            else:
                close_modal(driver)
                results["failed"].append(item)
                log.error(f"    FAIL: Save failed for '{cat}'")

            time.sleep(2)

    except KeyboardInterrupt:
        log.info("\n  Interrupted by user!")
    except Exception as e:
        log.error(f"\n  Unexpected error: {e}", exc_info=True)
    finally:
        log.info(f"\n\n{'=' * 70}")
        log.info(f"  RESULTS SUMMARY")
        log.info(f"{'=' * 70}")
        log.info(f"  Success:  {len(results['success']):3d}")
        log.info(f"  Failed:   {len(results['failed']):3d}")
        log.info(f"  Skipped:  {len(results['skipped']):3d}")

        if results["failed"]:
            log.info("\n  Failed categories:")
            for item in results["failed"]:
                log.info(f"    - {item['cat']} ({item['name']})")

        if results["skipped"]:
            log.info("\n  Skipped categories (not found):")
            for item in results["skipped"]:
                log.info(f"    - {item['cat']} ({item['name']})")

        results_file = SCRIPT_DIR / "playlist_upload_results.json"
        with results_file.open("w", encoding="utf-8") as f:
            json.dump({
                "success": [{"cat": i["cat"], "csv": i["name"], "rows": i["rows"]} for i in results["success"]],
                "failed":  [{"cat": i["cat"], "csv": i["name"], "rows": i["rows"]} for i in results["failed"]],
                "skipped": [{"cat": i["cat"], "csv": i["name"], "rows": i["rows"]} for i in results["skipped"]],
            }, f, indent=2)
        log.info(f"\n  Results: {results_file}")
        log.info(f"  Log:     {LOG_FILE}")

        input("\n  Press Enter to close browser...")
        driver.quit()


if __name__ == "__main__":
    main()
