"""
debug_upload.py — Opens browser, logs in, attaches files, takes screenshots
to understand what the admin page shows after upload (for job ID capture fix).
"""

import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from config import ADMIN_LOGIN_URL, ADMIN_UPLOAD_URL, BB_USERNAME, BB_PASSWORD, BATCHES_DIR

# File paths
CSV_PATH = os.path.join(BATCHES_DIR, "Batch_04.csv")
ZIP_PATH = os.path.join(BATCHES_DIR, "Batch_04.zip")
SHOT_DIR = os.path.join(os.path.dirname(__file__), "debug_shots")
os.makedirs(SHOT_DIR, exist_ok=True)

def shot(driver, name):
    p = os.path.join(SHOT_DIR, f"{name}.png")
    driver.save_screenshot(p)
    print(f"  Screenshot: {p}")

opts = Options()
opts.add_argument("--window-size=1400,900")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
wait = WebDriverWait(driver, 20)

try:
    # ── Login ──────────────────────────────────────────────────────────────────
    print("\n[1] Logging in ...")
    driver.get(ADMIN_LOGIN_URL)
    time.sleep(2)

    user = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "input[type='text'], input[name='username'], input[name='email']")
    ))
    user.clear(); user.send_keys(BB_USERNAME)
    pw = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
    pw.clear(); pw.send_keys(BB_PASSWORD)
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
    time.sleep(3)
    shot(driver, "01_after_login")
    print(f"  URL after login: {driver.current_url}")

    # ── Navigate to upload page ────────────────────────────────────────────────
    print("\n[2] Navigating to upload page ...")
    driver.get(ADMIN_UPLOAD_URL)
    time.sleep(3)
    shot(driver, "02_upload_page")

    # Print all visible text
    print("  Page title:", driver.title)
    print(f"  URL: {driver.current_url}")

    # ── Find and inspect radio buttons ────────────────────────────────────────
    print("\n[3] Inspecting radio buttons ...")
    labels = driver.find_elements(By.CSS_SELECTOR, "label")
    for i, l in enumerate(labels):
        print(f"  label[{i}]: '{l.text.strip()}'")

    # ── Find file inputs ──────────────────────────────────────────────────────
    print("\n[4] Inspecting file inputs ...")
    inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    for i, inp in enumerate(inputs):
        print(f"  input[{i}]: accept='{inp.get_attribute('accept')}' name='{inp.get_attribute('name')}'")

    # ── Select Entertainment radio ─────────────────────────────────────────────
    print("\n[5] Selecting Entertainment radio ...")
    for label in labels:
        if "entertainment" in label.text.lower():
            try:
                radio = label.find_element(By.CSS_SELECTOR, "input[type='radio']")
                driver.execute_script("arguments[0].click();", radio)
                print(f"  Selected: '{label.text.strip()}'")
            except:
                driver.execute_script("arguments[0].click();", label)
            break
    time.sleep(0.5)

    # ── Attach files ───────────────────────────────────────────────────────────
    print("\n[6] Attaching CSV and ZIP ...")
    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    for inp in file_inputs:
        driver.execute_script("arguments[0].style.display='block'; arguments[0].style.opacity='1';", inp)

    file_inputs[0].send_keys(CSV_PATH)
    print(f"  CSV attached: {os.path.basename(CSV_PATH)}")
    time.sleep(0.5)
    file_inputs[1].send_keys(ZIP_PATH)
    print(f"  ZIP attached: {os.path.basename(ZIP_PATH)}")
    time.sleep(1)
    shot(driver, "03_files_attached")

    # ── Find upload button ─────────────────────────────────────────────────────
    print("\n[7] Finding upload button ...")
    btns = driver.find_elements(By.CSS_SELECTOR, "button")
    for i, btn in enumerate(btns):
        print(f"  button[{i}]: '{btn.text.strip()}' disabled={btn.get_attribute('disabled')}")

    upload_btn = None
    for btn in btns:
        t = btn.text.strip().lower()
        if t == "upload" or ("upload" in t and "status" not in t and "check" not in t):
            upload_btn = btn
            break

    if not upload_btn:
        print("  ERROR: No upload button found!")
        shot(driver, "04_no_upload_btn")
    else:
        print(f"  Found upload button: '{upload_btn.text.strip()}'")
        driver.execute_script("arguments[0].click();", upload_btn)
        print("  Clicked upload button. Waiting for response...")

        # Wait longer and observe changes
        for i in range(1, 16):
            time.sleep(2)
            page_text = driver.find_element(By.TAG_NAME, "body").text
            page_url  = driver.current_url
            shot(driver, f"05_wait_{i:02d}s")
            print(f"\n  -- t={i*2}s -- URL: {page_url}")

            # Print first 500 chars of page text
            print(f"  Page text (first 500): {page_text[:500]}")

            # Save full page source
            src_file = os.path.join(SHOT_DIR, f"page_source_{i:02d}.html")
            with open(src_file, "w", encoding="utf-8") as f:
                f.write(driver.page_source)

            # Also specifically look for Job ID label/input
            print("  -- Scanning for Job ID label/input --")
            all_labels = driver.find_elements(By.CSS_SELECTOR, "label")
            for lbl in all_labels:
                if "job" in lbl.text.lower() or "id" in lbl.text.lower():
                    print(f"    label: '{lbl.text.strip()}'")
            all_inputs = driver.find_elements(By.CSS_SELECTOR, "input")
            for inp in all_inputs:
                v = inp.get_attribute("value") or ""
                ph = inp.get_attribute("placeholder") or ""
                nm = inp.get_attribute("name") or ""
                if v or nm or "job" in ph.lower():
                    print(f"    input name='{nm}' value='{v}' placeholder='{ph}'")
            # Look for any element with 'job' in id/class
            job_els = driver.find_elements(By.XPATH, "//*[contains(@id,'job') or contains(@class,'job') or contains(@id,'Job') or contains(@class,'Job')]")
            for el in job_els:
                print(f"    job-el tag={el.tag_name} id='{el.get_attribute('id')}' text='{el.text.strip()[:80]}'")

            # Stop early if we see obvious completion signals
            signals = ["job", "success", "upload", "error", "fail", "complete", "id"]
            if any(s in page_text.lower() for s in ["job id", "job_id", "jobid", "success", "uploaded"]):
                print("  ** Completion signal detected **")
                break

finally:
    print("\n\nDone. Check debug_shots/ folder for screenshots.")
    print("Browser will stay open. Close it to exit.")
    input("Press ENTER to close browser...")
    driver.quit()
