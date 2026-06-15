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
                "partially_failed", "partially failed",
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
    """Immediately stop any running upload. Kill Chrome processes aggressively."""
    global active_driver
    import subprocess as sp
    abort_event.set()  # Signal the polling loop to stop immediately
    log.info("Aborting active Selenium upload session...")

    # Force-kill ALL Chrome and chromedriver processes
    for proc_name in ("chromedriver", "chrome"):
        try:
            sp.run(
                ["taskkill", "/F", "/IM", f"{proc_name}.exe", "/T"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    active_driver = None
    log.info("Selenium abort complete — Chrome processes killed.")

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

    # Find the 'Submit Batch for Approval' button
    btns = driver.find_elements(By.CSS_SELECTOR, "button")
    approval_btn = None
    for btn in btns:
        txt = btn.text.strip().lower()
        if "submit" in txt and "approval" in txt:
            approval_btn = btn
            break

    if not approval_btn:
        log.error("  [APPROVAL] 'Submit Batch for Approval' button not found on page!")
        return False

    log.info(f"  [APPROVAL] Clicking 'Submit Batch for Approval'...")
    driver.execute_script("arguments[0].click();", approval_btn)
    time.sleep(2)

    # Poll for success or failure (up to 60 seconds)
    for poll in range(20):
        if abort_event.is_set():
            log.info("  [ABORT] Approval aborted by user.")
            return False

        time.sleep(3)
        try:
            body = driver.execute_script(
                "return document.body ? (document.body.innerText || '') : ''"
            ) or ""
            body_lower = body.lower()

            # Check for failure indicators
            for fail_pattern in (
                "failed to fetch", "network error", "error occurred",
                "something went wrong", "request failed", "server error",
                "internal server error", "502", "503", "504",
                "partially_failed", "partially failed",
            ):
                if fail_pattern in body_lower:
                    log.error(f"  [APPROVAL FAIL] Detected '{fail_pattern}' on page (poll #{poll+1})")
                    return False

            # Check for success indicators
            for success_pattern in (
                "successfully submitted", "batch submitted",
                "approved", "submission complete",
            ):
                if success_pattern in body_lower:
                    log.info(f"  [APPROVAL OK] Batch submitted for approval (poll #{poll+1})")
                    return True

            # If the approval button is gone and no error, likely success
            btns_now = driver.find_elements(By.CSS_SELECTOR, "button")
            still_there = any(
                "submit" in b.text.strip().lower() and "approval" in b.text.strip().lower()
                for b in btns_now
            )
            if not still_there:
                log.info(f"  [APPROVAL OK] Approval button disappeared — assuming success (poll #{poll+1})")
                return True

        except Exception as e:
            log.debug(f"  [APPROVAL] Poll error: {e}")

        log.info(f"  [APPROVAL POLL {poll+1}] Waiting for result...")

    log.warning("  [APPROVAL] Timed out waiting for approval result — assuming failure")
    return False


def run_all_and_submit(batch_names: list[str], headless: bool = False) -> dict[str, dict]:
    """
    Upload ALL batches, clicking 'Submit for Approval' after each.

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

            job_id = upload_batch(driver, batch_name)
            if not job_id:
                log.error(f"  [FAIL] Upload failed for {batch_name}")
                results[batch_name] = {"job_id": None, "status": "upload_failed"}
                time.sleep(3)
                continue

            log.info(f"  [OK] Uploaded: {batch_name} — Job ID: {job_id}")
            log.info(f"  [STEP 2] Now submitting for approval...")

            # The page should now show 'Processed Results' with the approval button
            approved = click_submit_for_approval(driver)
            if approved:
                log.info(f"  [OK] {batch_name} submitted for approval!")
                results[batch_name] = {"job_id": job_id, "status": "submitted"}
            else:
                log.error(f"  [FAIL] {batch_name} uploaded but approval failed!")
                results[batch_name] = {"job_id": job_id, "status": "approval_failed"}

            time.sleep(5)  # pause between batches

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
            # Get the Chrome PID and kill it
            import subprocess as sp
            if hasattr(driver, 'service') and hasattr(driver.service, 'process') and driver.service.process:
                pid = driver.service.process.pid
                sp.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=5)
        except Exception as e:
            log.debug(f"  Force-kill fallback error: {e}")
    log.info("  Selenium driver closed.")


def _try_quit(driver):
    """Attempt driver.quit() — used in a thread so we can timeout."""
    try:
        driver.quit()
    except Exception:
        pass
