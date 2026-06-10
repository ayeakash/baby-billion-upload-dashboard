"""
uploader.py -- Selenium-based uploader for admin.babybillion.in/dashboard/cms/bulk-upload

For each batch:
  1. Navigate to bulk-upload page (re-login if session expired)
  2. Select "Entertainment" radio button
  3. Attach CSV file to the CSV input
  4. Attach ZIP file to the ZIP input
  5. Click Upload
  6. Capture Job ID from the response
  7. Return job_id string (or None on failure)
"""
from __future__ import annotations

import os
import re
import time
import logging
import threading
from config import (
    ADMIN_LOGIN_URL, ADMIN_UPLOAD_URL,
    BB_USERNAME, BB_PASSWORD, UPLOAD_TYPE,
    SELENIUM_WAIT_SEC, UPLOAD_RETRY_MAX, BATCHES_DIR,
)

log = logging.getLogger(__name__)

# Event to manage pausing and resuming the upload thread
upload_resume_event = threading.Event()
upload_resume_event.set()

# Event to signal the polling loop to abort immediately
abort_event = threading.Event()

# ── Lazy Selenium import ───────────────────────────────────────────────────────
def _get_selenium():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException, NoSuchElementException
        from webdriver_manager.chrome import ChromeDriverManager
        return (webdriver, Options, Service, By, WebDriverWait, EC,
                TimeoutException, NoSuchElementException, ChromeDriverManager)
    except ImportError as e:
        raise ImportError(f"Selenium not installed: {e}\nRun: pip install selenium webdriver-manager")


def build_driver(headless: bool = False):
    webdriver, Options, Service, By, WebDriverWait, EC, _, _, ChromeDriverManager = _get_selenium()
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


def _wait_for(driver, By, EC, by, selector, timeout=SELENIUM_WAIT_SEC):
    from selenium.webdriver.support.ui import WebDriverWait
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, selector))
    )


def login(driver) -> bool:
    _, _, _, By, WebDriverWait, EC, TimeoutException, _, _ = _get_selenium()

    log.info("Navigating to login page …")
    driver.get(ADMIN_LOGIN_URL)
    time.sleep(2)

    if "/login" not in driver.current_url:
        log.info("Already logged in.")
        return True

    try:
        # Username field
        user_field = WebDriverWait(driver, SELENIUM_WAIT_SEC).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR, "input[type='text'], input[name='username'], input[name='email']"
            ))
        )
        user_field.clear()
        user_field.send_keys(BB_USERNAME)

        pass_field = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        pass_field.clear()
        pass_field.send_keys(BB_PASSWORD)

        btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        btn.click()
        log.info("Login button clicked. Waiting for redirect...")

        # Wait up to 15 seconds for URL to change (no longer contain /login)
        redirected = False
        for _ in range(15):
            time.sleep(1)
            if "/login" not in driver.current_url:
                redirected = True
                break

        if not redirected:
            log.error("Login failed -- still on login page. Check credentials.")
            return False

        log.info(f"Logged in. URL: {driver.current_url}")
        return True

    except Exception as e:
        log.error(f"Login error: {e}")
        return False


def _capture_job_id(driver) -> str | None:
    """
    Poll indefinitely (every 3s) until:
      - A UUID job ID is found  -> return it
      - An explicit upload error is detected -> return None immediately

    This is a React SPA so body.text only shows nav text.
    We use JS execute_script to read the actual rendered DOM.

    Known DOM structure:
      <p id="upload-error">...</p>  -- error text (empty = no error yet)
      After success a UUID appears in input values or span text.
    """
    uuid_pat = re.compile(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        re.IGNORECASE
    )

    # Collect all input values + short text snippets from the rendered DOM
    JS_COLLECT = """
var parts = [];
document.querySelectorAll('input, textarea').forEach(function(el) {
    var v = el.value || '';
    if (v) parts.push('INPUT:' + v);
});
document.querySelectorAll('p, span, div, h1, h2, h3, h4, li').forEach(function(el) {
    var t = (el.innerText || el.textContent || '').trim();
    if (t && t.length < 200) parts.push('TEXT:' + t);
});
return parts.join('\\n');
"""
    # Read the upload-error element specifically
    JS_ERROR = """
var el = document.getElementById('upload-error');
return el ? (el.innerText || el.textContent || '').trim() : '';
"""

    MAX_POLLS = 200   # 200 × 3s = 10 min hard cap
    poll_num = 0
    consecutive_driver_errors = 0
    while poll_num < MAX_POLLS:
        upload_resume_event.wait()

        # Check if abort was requested (user clicked Stop Upload)
        if abort_event.is_set():
            log.info("  [ABORT] Upload aborted by user.")
            return None

        poll_num += 1
        time.sleep(3)

        if abort_event.is_set():
            log.info("  [ABORT] Upload aborted by user.")
            return None

        # ── Check for explicit server error ──────────────────────────────────
        try:
            err_text = driver.execute_script(JS_ERROR) or ""
            if err_text and len(err_text) > 2:
                log.warning(f"  [ERROR] Upload error on page (poll #{poll_num}): {err_text}")
                return None
            consecutive_driver_errors = 0  # reset on successful communication
        except Exception:
            consecutive_driver_errors += 1
            if consecutive_driver_errors >= 3:
                log.error(f"  [ERROR] Browser appears to have crashed ({consecutive_driver_errors} consecutive driver errors). Aborting.")
                return None

        # ── Scan all inputs + text elements via JS ───────────────────────────
        try:
            collected = driver.execute_script(JS_COLLECT) or ""
            m = uuid_pat.search(collected)
            if m:
                log.info(f"  [JOB ID] Found via JS scan (poll #{poll_num}): {m.group(1)}")
                return m.group(1)
            consecutive_driver_errors = 0
        except Exception as js_err:
            log.debug(f"  JS collect failed: {js_err}")
            collected = ""

        # ── Fallback: scan raw page source for UUID ──────────────────────────
        try:
            m = uuid_pat.search(driver.page_source)
            if m:
                log.info(f"  [JOB ID] Found in page source (poll #{poll_num}): {m.group(1)}")
                return m.group(1)
        except Exception:
            pass

        log.info(f"  [POLL {poll_num}] t={poll_num * 3}s | waiting for job ID or error ...")

    log.error(f"  [TIMEOUT] No job ID after {MAX_POLLS * 3}s ({MAX_POLLS} polls) -- giving up.")
    return None


def upload_batch(driver, batch_name: str) -> str | None:
    """
    Upload one batch. Returns job_id or None.
    Retries up to UPLOAD_RETRY_MAX times.
    """
    _, _, _, By, WebDriverWait, EC, TimeoutException, NoSuchElementException, _ = _get_selenium()

    csv_path = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
    zip_path = os.path.join(BATCHES_DIR, f"{batch_name}.zip")

    if not os.path.isfile(csv_path):
        log.error(f"  CSV missing: {csv_path}")
        return None
    if not os.path.isfile(zip_path):
        log.error(f"  ZIP missing: {zip_path}")
        return None

    for attempt in range(1, UPLOAD_RETRY_MAX + 1):
        log.info(f"  Upload attempt {attempt}/{UPLOAD_RETRY_MAX} for {batch_name} …")
        try:
            job_id = _do_upload(driver, By, WebDriverWait, EC,
                                NoSuchElementException, csv_path, zip_path, batch_name)
            if job_id:
                return job_id
        except Exception as e:
            log.warning(f"  Attempt {attempt} error: {e}")
            # Take screenshot for debugging
            try:
                ss = os.path.join(BATCHES_DIR, f"error_{batch_name}_attempt{attempt}.png")
                driver.save_screenshot(ss)
            except Exception:
                pass
        time.sleep(5)

    return None


def _do_upload(driver, By, WebDriverWait, EC, NoSuchElementException,
               csv_path: str, zip_path: str, batch_name: str) -> str | None:
    driver.get(ADMIN_UPLOAD_URL)
    time.sleep(2)

    # Re-login if redirected
    if "/login" in driver.current_url:
        log.warning("  Session expired -- re-logging in …")
        if not login(driver):
            return None
        driver.get(ADMIN_UPLOAD_URL)
        time.sleep(2)

    # ── Find file inputs ────────────────────────────────────────────────────────
    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    if len(file_inputs) < 2:
        log.error("  Could not find 2 file inputs on page!")
        return None

    csv_input, zip_input = None, None
    for inp in file_inputs:
        accept = (inp.get_attribute("accept") or "").lower()
        if "csv" in accept or "text" in accept:
            csv_input = inp
        elif "zip" in accept or "application" in accept:
            zip_input = inp

    # Positional fallback
    if not csv_input:
        csv_input = file_inputs[0]
    if not zip_input:
        zip_input = file_inputs[1]

    # Make inputs interactable (some are hidden)
    driver.execute_script("arguments[0].style.display = 'block'; arguments[0].style.opacity = '1';", csv_input)
    driver.execute_script("arguments[0].style.display = 'block'; arguments[0].style.opacity = '1';", zip_input)

    csv_input.send_keys(csv_path)
    log.info(f"  [OK] CSV attached: {os.path.basename(csv_path)}")
    time.sleep(0.5)

    zip_input.send_keys(zip_path)
    log.info(f"  [OK] ZIP attached: {os.path.basename(zip_path)}")
    time.sleep(1)

    # ── Click Submit/Upload button ─────────────────────────────────────────────
    upload_btn = None
    btns = driver.find_elements(By.CSS_SELECTOR, "button")

    # Priority 1: Look for the exact "Submit & Process" button
    for btn in btns:
        txt = btn.text.strip().lower()
        if "submit" in txt and "process" in txt:
            upload_btn = btn
            break

    # Priority 2: Any button with "submit" in the text
    if not upload_btn:
        for btn in btns:
            txt = btn.text.strip().lower()
            if "submit" in txt:
                upload_btn = btn
                break

    # Priority 3: Button with "process" (but not just a tab/nav button)
    if not upload_btn:
        for btn in btns:
            txt = btn.text.strip().lower()
            if "process" in txt and len(txt) > 5:
                upload_btn = btn
                break

    if not upload_btn:
        log.error("  Could not find Submit & Process / Upload button!")
        return None

    driver.execute_script("arguments[0].click();", upload_btn)
    log.info("  >> Submit & Process button clicked -- waiting for Job ID …")
    time.sleep(2)  # brief settle before polling starts

    # ── Capture Job ID (polls until success or explicit error) ───────────────
    return _capture_job_id(driver)


active_driver = None

def abort():
    global active_driver
    abort_event.set()  # Signal the polling loop to stop immediately
    if active_driver:
        log.info("Aborting active Selenium upload session...")
        try:
            active_driver.quit()
        except Exception:
            pass
        active_driver = None

def run_all(batch_names: list[str], headless: bool = False) -> dict[str, str | None]:
    """
    Upload all batches. Returns {batch_name: job_id | None}.
    """
    global active_driver
    if not BB_USERNAME or not BB_PASSWORD:
        raise ValueError(
            "BB_USERNAME and BB_PASSWORD must be set.\n"
            "Run:\n"
            "  $env:BB_USERNAME = 'your_username'\n"
            "  $env:BB_PASSWORD = 'your_password'"
        )

    abort_event.clear()  # Reset abort flag for new upload session
    driver    = build_driver(headless)
    active_driver = driver
    job_ids   = {}
    logged_in = False

    try:
        logged_in = login(driver)
        if not logged_in:
            log.error("Cannot proceed -- login failed.")
            return {}

        for batch_name in batch_names:
            upload_resume_event.wait()
            log.info(f"\n{'='*55}")
            log.info(f"  Uploading: {batch_name}")
            job_id = upload_batch(driver, batch_name)
            job_ids[batch_name] = job_id
            if job_id:
                log.info(f"  [OK] Job ID: {job_id}")
            else:
                log.error(f"  [FAIL] Upload failed for {batch_name}")
            time.sleep(5)   # polite pause between batches

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        active_driver = None

    return job_ids
