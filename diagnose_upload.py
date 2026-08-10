"""
Diagnose why uploads are failing
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

print("\n" + "="*80)
print("DIAGNOSING UPLOAD FAILURE")
print("="*80 + "\n")

print("[1] Initializing Chrome...")
options = Options()
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--start-maximized")
driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, 30)

print("[2] Logging in...")
driver.get(LOGIN_URL)
time.sleep(3)

try:
    username_input = wait.until(EC.presence_of_element_located((By.ID, "username")))
    print("  ✓ Found username field")
    username_input.clear()
    username_input.send_keys(CMS_EMAIL)
    time.sleep(1)

    password_input = driver.find_element(By.ID, "password")
    print("  ✓ Found password field")
    password_input.clear()
    password_input.send_keys(CMS_PASSWORD)
    time.sleep(1)

    login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    print("  ✓ Found login button")
    login_button.click()
    print("  ✓ Clicked login button")

    for i in range(30):
        try:
            driver.find_element(By.XPATH, "//a[contains(@href, '/playlists')]")
            print("  ✓ Login successful\n")
            time.sleep(2)
            break
        except:
            time.sleep(1)
except Exception as e:
    print(f"  ✗ Login failed: {str(e)}\n")
    driver.quit()
    exit()

print("[3] Navigating to categories...")
driver.get(CATEGORIES_URL)
time.sleep(4)
print("  ✓ Loaded categories page\n")

print("[4] Testing search for 'Learn Your ABC'...")
try:
    search_box = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']"))
    )
    print("  ✓ Found search box")
    search_box.clear()
    search_box.send_keys("Learn Your ABC")
    time.sleep(3)
    print("  ✓ Entered search text\n")
except Exception as e:
    print(f"  ✗ Search failed: {str(e)}\n")
    driver.quit()
    exit()

print("[5] Clicking Edit button...")
try:
    edit_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]"))
    )
    print("  ✓ Found Edit button")
    edit_button.click()
    time.sleep(4)
    print("  ✓ Clicked Edit button\n")
except Exception as e:
    print(f"  ✗ Edit click failed: {str(e)}\n")
    driver.quit()
    exit()

print("[6] Looking for file inputs...")
try:
    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    print(f"  ✓ Found {len(file_inputs)} file input fields\n")

    if len(file_inputs) > 0:
        print("[7] File inputs found - ready to upload")
        print("  ✓ Upload mechanism is available\n")
    else:
        print("  ✗ No file inputs found - check page structure\n")
except Exception as e:
    print(f"  ✗ File input search failed: {str(e)}\n")

driver.quit()
print("="*80)
print("DIAGNOSIS COMPLETE")
print("="*80 + "\n")
