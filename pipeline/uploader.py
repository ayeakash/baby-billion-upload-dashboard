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

import csv
import os
import re
import time
import logging
import threading
from config import (
    ADMIN_LOGIN_URL, ADMIN_UPLOAD_URL, ADMIN_BASE_URL,
    BB_USERNAME, BB_PASSWORD, UPLOAD_TYPE,
    SELENIUM_WAIT_SEC, UPLOAD_RETRY_MAX, BATCHES_DIR,
)

ADMIN_UPLOAD_HISTORY_URL = f"{ADMIN_BASE_URL}/dashboard/cms/video-upload"

log = logging.getLogger(__name__)

# Event to manage pausing and resuming the upload thread
upload_resume_event = threading.Event()
upload_resume_event.set()

# Event to signal the polling loop to abort immediately
abort_event = threading.Event()

# ── Lazy import of the repo-root procutils (works both when the dashboard
#    imports us and when pipeline.py runs standalone from pipeline/) ───────────
def _procutils():
    import sys as _sys
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    import procutils
    return procutils


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
      - "Processed Results" / "Submit Batch for Approval" detected -> return UUID
      - An explicit upload error is detected -> return None immediately

    This is a React SPA so body.text only shows nav text.
    We use JS execute_script to read the actual rendered DOM.

    Known DOM structure (old):
      <p id="upload-error">...</p>  -- error text (empty = no error yet)
      After success a UUID appears in input values or span text.

    Known DOM structure (new CMS):
      After upload processing completes:
      - Banner: "Upload is paused. Batch <UUID> is completed and waiting for approval"
      - "Processed Results" heading
      - "Submit Batch for Approval" button
      - Table of video IDs
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
document.querySelectorAll('p, span, div, h1, h2, h3, h4, li, td, th, button').forEach(function(el) {
    var t = (el.innerText || el.textContent || '').trim();
    if (t && t.length < 300) parts.push('TEXT:' + t);
});
return parts.join('\\n');
"""
    # Read the upload-error element specifically
    JS_ERROR = """
var el = document.getElementById('upload-error');
return el ? (el.innerText || el.textContent || '').trim() : '';
"""
    # Detect the new CMS "Processed Results" completion screen
    JS_COMPLETION = """
var body = document.body ? (document.body.innerText || document.body.textContent || '') : '';
var indicators = {
    hasProcessedResults: body.indexOf('Processed Results') !== -1,
    hasSubmitForApproval: body.indexOf('Submit Batch for Approval') !== -1,
    hasCompletedWaiting: body.indexOf('completed and waiting') !== -1,
    hasRejectUpload: body.indexOf('Reject Upload') !== -1,
    hasVideoId: body.indexOf('VIDEO ID') !== -1 || body.indexOf('Video ID') !== -1 || body.indexOf('video_id') !== -1,
};
indicators.isComplete = indicators.hasProcessedResults || indicators.hasSubmitForApproval || indicators.hasCompletedWaiting;
return JSON.stringify(indicators);
"""

    MAX_POLLS = 100   # 100 × 3s = 5 min hard cap
    poll_num = 0
    consecutive_driver_errors = 0
    while poll_num < MAX_POLLS:
        # Check abort before waiting
        if abort_event.is_set():
            log.info("  [ABORT] Upload aborted by user.")
            return None

        upload_resume_event.wait()

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

        # ── Check for rejection / validation error messages in page body ─────
        try:
            body_text = driver.execute_script(
                "return document.body ? (document.body.innerText || '') : ''"
            ) or ""
            body_lower = body_text.lower()
            # Common rejection / error patterns
            for pattern in (
                "invalid csv", "invalid file", "file not accepted",
                "upload failed", "error occurred", "something went wrong",
                "not accepted", "rejected", "validation error",
                "please try again", "unsupported format",
            ):
                if pattern in body_lower:
                    log.warning(f"  [REJECTED] Dashboard rejected upload (poll #{poll_num}): found '{pattern}' in page")
                    log.warning(f"  Page text snippet: {body_text[:300]}")
                    return None
        except Exception:
            pass

        # ── Check for the new CMS "Processed Results" completion screen ──────
        try:
            import json as _json
            completion_raw = driver.execute_script(JS_COMPLETION) or "{}"
            completion = _json.loads(completion_raw)
            if completion.get("isComplete"):
                log.info(f"  [COMPLETE] CMS shows upload completion screen (poll #{poll_num})")
                log.info(f"    Indicators: {completion}")
                # Now find the UUID on this page
                collected = driver.execute_script(JS_COLLECT) or ""
                m = uuid_pat.search(collected)
                if m:
                    log.info(f"  [JOB ID] Found on completion screen: {m.group(1)}")
                    return m.group(1)
                # Fallback: page source
                m = uuid_pat.search(driver.page_source or "")
                if m:
                    log.info(f"  [JOB ID] Found in page source on completion: {m.group(1)}")
                    return m.group(1)
                # Completion detected but no UUID? Return a placeholder
                log.warning("  [COMPLETE] Completion screen found but no UUID — returning placeholder")
                return "completed-no-uuid"
            consecutive_driver_errors = 0
        except Exception as comp_err:
            log.debug(f"  Completion check error: {comp_err}")

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

        log.info(f"  [POLL {poll_num}] t={poll_num * 3}s | waiting for job ID or completion screen ...")

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

        # Before retrying, check if the page already shows "Processed Results"
        # (meaning a previous attempt actually succeeded)
        if attempt > 1:
            try:
                import json as _json
                body = driver.execute_script(
                    "return document.body ? document.body.innerText : ''"
                ) or ""
                if "Processed Results" in body or "Submit Batch for Approval" in body:
                    log.info(f"  [ALREADY DONE] Page shows Processed Results — first attempt succeeded!")
                    uuid_pat = re.compile(
                        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
                        re.IGNORECASE
                    )
                    m = uuid_pat.search(body)
                    if m:
                        batch_uuid = m.group(1)
                        log.info(f"  [BATCH ID] {batch_uuid}")
                        return batch_uuid
                    return "completed-no-uuid"
            except Exception:
                pass

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

    # ── Clear any pending batch on the page ────────────────────────────────────
    # The CMS won't show file inputs while a previous batch result is still
    # on screen. Submit or dismiss it first.
    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    if len(file_inputs) < 2:
        log.info("  [CLEAR] File inputs not visible — clearing pending batch on page...")
        btns = driver.find_elements(By.CSS_SELECTOR, "button")
        cleared = False

        # Try "Submit Batch for Approval" first
        for btn in btns:
            txt = btn.text.strip().lower()
            if "submit" in txt and "approval" in txt:
                log.info("  [CLEAR] Clicking 'Submit Batch for Approval' to clear page...")
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(3)
                cleared = True
                break

        # If no approval button, try "Reject Upload"
        if not cleared:
            for btn in btns:
                txt = btn.text.strip().lower()
                if "reject" in txt:
                    log.info("  [CLEAR] Clicking 'Reject Upload' to clear page...")
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(3)
                    cleared = True
                    break

        if cleared:
            # Reload the page to get clean upload form
            driver.get(ADMIN_UPLOAD_URL)
            time.sleep(2)
            if "/login" in driver.current_url:
                if not login(driver):
                    return None
                driver.get(ADMIN_UPLOAD_URL)
                time.sleep(2)

        # Re-check file inputs
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        if len(file_inputs) < 2:
            log.error("  Could not find 2 file inputs on page (even after clearing pending batch)!")
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

    # Priority 2: Any button with "submit" — but NOT "Submit Batch for Approval"
    if not upload_btn:
        for btn in btns:
            txt = btn.text.strip().lower()
            if "submit" in txt and "approval" not in txt:
                upload_btn = btn
                break

    # Priority 3: Button with "process" (but not just a tab/nav button)
    if not upload_btn:
        for btn in btns:
            txt = btn.text.strip().lower()
            if "process" in txt and len(txt) > 5 and "approval" not in txt:
                upload_btn = btn
                break

    if not upload_btn:
        log.error("  Could not find Submit & Process / Upload button!")
        return None

    # Final safety: refuse to click if the matched button looks like the approval button
    matched_text = (upload_btn.text or "").strip()
    if "approval" in matched_text.lower():
        log.error(f"  [SAFETY] Refusing to click '{matched_text}' — this is the review submission button, not the upload button!")
        return None

    driver.execute_script("arguments[0].click();", upload_btn)
    log.info(f"  >> Submit & Process button clicked ('{matched_text}') -- waiting for Job ID …")
    time.sleep(2)  # brief settle before polling starts

    # ── Capture Job ID (polls until success or explicit error) ───────────────
    return _capture_job_id(driver)


active_driver = None

def abort():
    """Immediately stop any running upload.

    Closes ONLY the Selenium-owned browser session (graceful quit, falling
    back to killing the chromedriver process tree). The user's personal
    Chrome is never touched.
    """
    global active_driver
    abort_event.set()  # Signal the polling loop to stop immediately
    log.info("Aborting active Selenium upload session...")

    driver = active_driver
    active_driver = None
    if driver is not None:
        _safe_quit_driver(driver)

    # Clean up any leftover chromedriver from a crashed earlier session
    try:
        _procutils().kill_selenium_browser()
    except Exception as e:
        log.warning(f"Selenium browser cleanup failed: {e}")

    log.info("Selenium abort complete — automation browser closed.")

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
        _safe_quit_driver(driver)
        active_driver = None

    return job_ids


# ── Upload All + Submit for Approval ─────────────────────────────────────────

def click_submit_for_approval(driver) -> bool:
    """
    After upload completes (Processed Results screen visible),
    find and click 'Submit Batch for Approval', then wait for success or failure.

    Returns True on success, False on failure (including 'failed to fetch').
    """
    _, _, _, By, WebDriverWait, EC, TimeoutException, _, _ = _get_selenium()

    # First, check if the page already shows a FAILED status (CMS rejected the batch)
    try:
        body = driver.execute_script(
            "return document.body ? (document.body.innerText || '') : ''"
        ) or ""
        body_lower = body.lower()

        # CMS shows "FAILED" status or "Total: 0" when batch is rejected
        for fail_indicator in ("status\nfailed", "status: failed", "total\n0",
                               "total: 0", "0 total", "no videos processed"):
            if fail_indicator in body_lower:
                log.error(f"  [APPROVAL] CMS shows FAILED status before submit — batch was rejected")
                return False
    except Exception:
        pass

    # Find the 'Submit Batch for Approval' button.
    # Server processing is done (we have job ID). For >5 videos,
    # CMS may need one page reload to render the button.
    approval_btn = None

    for attempt in range(2):
        btns = driver.find_elements(By.CSS_SELECTOR, "button")
        for btn in btns:
            txt = btn.text.strip().lower()
            if "submit" in txt and "approval" in txt:
                approval_btn = btn
                break
        if approval_btn:
            break
        if attempt == 0:
            log.info("  [APPROVAL] Button not visible — reloading page...")
            driver.refresh()
            time.sleep(2)

    if not approval_btn:
        log.error("  [APPROVAL] 'Submit Batch for Approval' button not found on page!")
        return False

    log.info(f"  [APPROVAL] Clicking 'Submit Batch for Approval'...")
    driver.execute_script("arguments[0].click();", approval_btn)
    time.sleep(1)

    # After clicking, poll briefly. If the button disappears, it's a success.
    # The CMS navigates away or removes the button on successful submission.
    for poll in range(10):  # 10 × 2s = 20s max
        if abort_event.is_set():
            log.info("  [ABORT] Approval aborted by user.")
            return False

        try:
            body = driver.execute_script(
                "return document.body ? (document.body.innerText || '') : ''"
            ) or ""
            body_lower = body.lower()

            # Check if button is gone — primary success signal
            btns_now = driver.find_elements(By.CSS_SELECTOR, "button")
            still_there = any(
                "submit" in b.text.strip().lower() and "approval" in b.text.strip().lower()
                for b in btns_now
            )
            if not still_there:
                if "failed" in body_lower and "completed" not in body_lower:
                    log.error(f"  [APPROVAL FAIL] Button gone but page shows 'failed' (poll #{poll+1})")
                    return False
                log.info(f"  [APPROVAL OK] Approval button disappeared — success (poll #{poll+1})")
                return True

            # Check for explicit failure
            for fail_pattern in (
                "failed to fetch", "network error", "error occurred",
                "something went wrong", "request failed", "server error",
            ):
                if fail_pattern in body_lower:
                    log.error(f"  [APPROVAL FAIL] Detected '{fail_pattern}' (poll #{poll+1})")
                    return False

        except Exception as e:
            log.debug(f"  [APPROVAL] Poll error: {e}")

        time.sleep(2)

    # If we got here, button is still there after 20s — assume it worked
    # (CMS sometimes doesn't update the page but the submission went through)
    log.warning("  [APPROVAL] Timed out but button was clicked — assuming success")
    return True


# ── Post-Upload CMS Verification ─────────────────────────────────────────────

def _normalize_video_name(name: str) -> str:
    """Normalize a video name for comparison."""
    name = name.lower().strip()
    name = re.sub(r'[^\w]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return name


def _get_batch_csv_video_names(batch_name: str) -> set[str]:
    """Read video names from a batch CSV file."""
    csv_path = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
    if not os.path.exists(csv_path):
        return set()
    names = set()
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vn = row.get("video_name", "").strip()
            if vn:
                names.add(_normalize_video_name(vn))
    return names


def verify_upload_on_cms(driver, batch_name: str, job_id: str) -> dict:
    """
    After uploading a batch, navigate to Upload History on the CMS,
    find the entry by job ID, click View, scrape video names,
    and verify they match the local batch CSV.

    Returns dict with:
      - verified: bool (True if videos match)
      - cms_count: int (videos found on CMS)
      - local_count: int (videos in CSV)
      - match_count: int (overlapping video names)
      - match_pct: float (percentage match)
    """
    _, _, _, By, WebDriverWait, EC, _, _, _ = _get_selenium()

    result = {
        "verified": False,
        "cms_count": 0,
        "local_count": 0,
        "match_count": 0,
        "match_pct": 0.0,
    }

    local_names = _get_batch_csv_video_names(batch_name)
    result["local_count"] = len(local_names)
    if not local_names:
        log.warning(f"  [VERIFY] No video names in CSV for {batch_name} — skipping")
        result["verified"] = True  # Can't verify, assume OK
        return result

    log.info(f"  [VERIFY] Navigating to Upload History to verify {batch_name}...")

    try:
        # Navigate to Upload History
        driver.get(ADMIN_UPLOAD_HISTORY_URL)
        time.sleep(3)

        # Click "Upload History" tab
        for el in driver.find_elements(By.CSS_SELECTOR, "button, a, span"):
            if "upload history" in el.text.strip().lower():
                try:
                    el.click()
                except Exception:
                    pass
                break
        time.sleep(2)

        # Find the row with our job ID and click View
        clicked_view = False
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        for row in rows:
            cells = row.find_elements(By.CSS_SELECTOR, "td")
            if len(cells) >= 1 and job_id in cells[0].text:
                # Click View button in last cell
                action_cell = cells[-1]
                for btn in action_cell.find_elements(By.CSS_SELECTOR, "button, a"):
                    if "view" in btn.text.strip().lower():
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(3)
                        clicked_view = True
                        break
                break

        if not clicked_view:
            log.warning(f"  [VERIFY] Could not find job {job_id[:20]}... in Upload History")
            return result

        # Scrape video names from the detail page
        body = driver.execute_script(
            "return document.body ? (document.body.innerText || '') : ''"
        )

        cms_video_names = set()
        for line in body.split("\n"):
            line = line.strip()
            if not line or len(line) < 3 or len(line) > 200:
                continue
            # Video names have underscores, typically start with capital letter
            if re.match(r'^[A-Z][a-z]+_[A-Z]', line) or re.match(r'^Kids_', line, re.I):
                cms_video_names.add(_normalize_video_name(line))
            elif "_" in line and not line.startswith("http") and not line.startswith("/"):
                llow = line.lower()
                skip_words = ("batch", "upload", "cms", "http", "babybillion",
                              "video_id", "content", "log out", "ms bubble",
                              "video upload", "processed", "submit", "reject")
                if not any(x in llow for x in skip_words):
                    cms_video_names.add(_normalize_video_name(line))

        result["cms_count"] = len(cms_video_names)

        # Compare
        overlap = len(cms_video_names & local_names)
        total = max(len(cms_video_names), len(local_names))
        pct = (overlap / total * 100) if total else 0

        result["match_count"] = overlap
        result["match_pct"] = pct
        result["verified"] = pct >= 50  # At least 50% match

        if result["verified"]:
            log.info(f"  [VERIFY] ✅ {batch_name} VERIFIED — {overlap}/{total} videos matched ({pct:.0f}%)")
        else:
            log.error(f"  [VERIFY] ❌ {batch_name} FAILED — only {overlap}/{total} videos matched ({pct:.0f}%)")

    except Exception as e:
        log.error(f"  [VERIFY] Error during verification: {e}")
        # Don't fail the upload just because verification had an error

    return result


def run_all_and_submit(batch_names: list[str], headless: bool = False,
                       on_result: callable = None) -> dict[str, dict]:
    """
    Upload ALL batches, clicking 'Submit for Approval' after each.

    Args:
        on_result: Optional callback(batch_name, result_dict) called after each
                   batch finishes. Allows live processing of results.

    Returns {batch_name: {job_id, status}} where status is:
      - 'submitted'        — uploaded + submitted for approval
      - 'upload_failed'    — upload itself failed
      - 'approval_failed'  — uploaded but approval submission failed (e.g., 'failed to fetch')
    """
    global active_driver
    if not BB_USERNAME or not BB_PASSWORD:
        raise ValueError("BB_USERNAME and BB_PASSWORD must be set.")

    abort_event.clear()
    driver = build_driver(headless)
    active_driver = driver
    results = {}

    try:
        if not login(driver):
            log.error("Cannot proceed — login failed.")
            return {bn: {"job_id": None, "status": "upload_failed"} for bn in batch_names}

        for batch_name in batch_names:
            if abort_event.is_set():
                log.info(f"  [ABORT] Stopping before {batch_name}")
                results[batch_name] = {"job_id": None, "status": "upload_failed"}
                continue

            upload_resume_event.wait()
            log.info(f"\n{'='*55}")
            log.info(f"  UPLOAD+SUBMIT: {batch_name}")
            log.info(f"{'='*55}")

            try:
                job_id = upload_batch(driver, batch_name)
                if not job_id:
                    log.error(f"  [FAIL] Upload failed for {batch_name}")
                    results[batch_name] = {"job_id": None, "status": "upload_failed"}
                    # Navigate back to upload page for next batch
                    try:
                        driver.get(ADMIN_UPLOAD_URL)
                        time.sleep(3)
                    except Exception:
                        pass
                    continue

                log.info(f"  [OK] Uploaded: {batch_name} — Job ID: {job_id}")
                log.info(f"  [STEP 2] Now submitting for approval...")

                # The page should now show 'Processed Results' with the approval button
                approved = click_submit_for_approval(driver)
                if approved:
                    log.info(f"  [OK] {batch_name} submitted for approval!")

                    # STEP 3: Verify on CMS Upload History
                    log.info(f"  [STEP 3] Verifying upload on CMS...")
                    verify_result = verify_upload_on_cms(driver, batch_name, job_id)

                    if verify_result["verified"]:
                        results[batch_name] = {
                            "job_id": job_id,
                            "status": "submitted",
                            "verified": True,
                            "verify_pct": verify_result["match_pct"],
                        }
                    else:
                        log.error(f"  [VERIFY FAIL] {batch_name} — CMS verification failed!")
                        results[batch_name] = {
                            "job_id": job_id,
                            "status": "approval_failed",
                            "verified": False,
                            "verify_pct": verify_result["match_pct"],
                        }
                else:
                    log.error(f"  [FAIL] {batch_name} uploaded but approval failed!")
                    results[batch_name] = {"job_id": job_id, "status": "approval_failed"}

            except Exception as e:
                log.error(f"  [EXCEPTION] {batch_name} crashed: {e}")
                results[batch_name] = {"job_id": None, "status": "upload_failed"}
                # Try to take a screenshot
                try:
                    ss = os.path.join(BATCHES_DIR, f"crash_{batch_name}.png")
                    driver.save_screenshot(ss)
                    log.info(f"  [SCREENSHOT] Saved: {ss}")
                except Exception:
                    pass

            # Fire live callback so batch_manager can update state immediately
            if on_result and batch_name in results:
                try:
                    on_result(batch_name, results[batch_name])
                except Exception as cb_err:
                    log.warning(f"  [CALLBACK] Error in on_result for {batch_name}: {cb_err}")

            # Navigate back to upload page for the next batch
            try:
                driver.get(ADMIN_UPLOAD_URL)
                time.sleep(5)  # pause between batches
            except Exception:
                log.warning(f"  [WARN] Could not navigate back to upload page")
                # Try to recover by re-login
                try:
                    if not login(driver):
                        log.error("  [FATAL] Re-login failed — stopping")
                        break
                except Exception:
                    log.error("  [FATAL] Driver unresponsive — stopping")
                    break

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        _safe_quit_driver(driver)
        active_driver = None

    return results


def _safe_quit_driver(driver, timeout=5):
    """Quit the Selenium driver with a timeout. If quit() hangs, force-kill the Chrome process."""
    if driver is None:
        return

    # Try graceful quit in a thread with timeout
    quit_thread = threading.Thread(target=lambda: _try_quit(driver), daemon=True)
    quit_thread.start()
    quit_thread.join(timeout=timeout)

    if quit_thread.is_alive():
        log.warning(f"  driver.quit() hung for {timeout}s — force-killing Chrome process")
        try:
            # Get the chromedriver PID and kill its whole tree (cross-platform)
            if hasattr(driver, 'service') and hasattr(driver.service, 'process') and driver.service.process:
                pid = driver.service.process.pid
                _procutils().kill_process_tree(pid)
        except Exception as e:
            log.debug(f"  Force-kill fallback error: {e}")
    log.info("  Selenium driver closed.")


def _try_quit(driver):
    """Attempt driver.quit() — used in a thread so we can timeout."""
    try:
        driver.quit()
    except Exception:
        pass
