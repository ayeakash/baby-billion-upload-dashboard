"""
Diagnose Home View upload field structure
"""

import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

CMS_EMAIL = "Intern@babybillion.in"
CMS_PASSWORD = "57zQfDqS8ZN8bR2"

LOGIN_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com"
CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"

def diagnose():
    print("\n" + "="*80)
    print("DIAGNOSING HOME VIEW UPLOAD STRUCTURE")
    print("="*80 + "\n")

    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 30)

    try:
        # Login
        print("[1] Logging in...")
        driver.get(LOGIN_URL)
        time.sleep(3)
        username = wait.until(EC.presence_of_element_located((By.ID, "username")))
        username.send_keys(CMS_EMAIL)
        time.sleep(1)
        password = driver.find_element(By.ID, "password")
        password.send_keys(CMS_PASSWORD)
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(5)
        print("  [OK] Logged in")

        # Navigate to categories
        print("[2] Going to categories...")
        driver.get(CATEGORIES_URL)
        time.sleep(4)
        print("  [OK] Categories page loaded")

        # Search for a category
        print("[3] Searching for 'Aladdin'...")
        search_box = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']"))
        )
        search_box.clear()
        search_box.send_keys("Aladdin")
        time.sleep(3)
        print("  [OK] Search entered")

        # Click edit
        print("[4] Clicking Edit button...")
        edit_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]"))
        )
        edit_btn.click()
        time.sleep(5)
        print("  [OK] Edit page loaded")

        # Check file inputs
        print("[5] Analyzing file input fields...")
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        print(f"  Found {len(file_inputs)} file input fields")

        for i, fi in enumerate(file_inputs):
            print(f"\n  Input {i}:")
            print(f"    - Element: {fi.tag_name}")
            print(f"    - ID: {fi.get_attribute('id')}")
            print(f"    - Name: {fi.get_attribute('name')}")
            print(f"    - Class: {fi.get_attribute('class')}")

        # Check for upload buttons
        print("\n[6] Checking Upload buttons...")
        upload_buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Upload')]")
        print(f"  Found {len(upload_buttons)} Upload buttons")

        for i, btn in enumerate(upload_buttons):
            print(f"\n  Button {i}:")
            print(f"    - Text: {btn.text}")
            print(f"    - Class: {btn.get_attribute('class')}")
            parent = btn.find_element(By.XPATH, "..")
            print(f"    - Parent class: {parent.get_attribute('class')}")

        # Check page structure
        print("\n[7] Checking page HTML structure...")
        thumbnails = driver.find_elements(By.XPATH, "//*[contains(text(), 'THUMBNAILS')]")
        print(f"  Found {len(thumbnails)} THUMBNAILS sections")

        views = driver.find_elements(By.XPATH, "//*[contains(text(), 'view')]")
        print(f"  Found {len(views)} 'view' text elements")
        for v in views:
            print(f"    - {v.text}")

    finally:
        driver.quit()

    print("\n" + "="*80)
    print("DIAGNOSIS COMPLETE")
    print("="*80 + "\n")

if __name__ == "__main__":
    diagnose()
