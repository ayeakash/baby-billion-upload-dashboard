"""
Test Uploader - Upload ONE character to test the automation
This is a safe test before running the full automation
"""

import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# Configuration
BASE_DIR = r"C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard"
PROCESSED_IMAGES_DIR = os.path.join(BASE_DIR, "processed_images")

# Credentials
CMS_EMAIL = "Intern@babybillion.in"
CMS_PASSWORD = "57zQfDqS8ZN8bR2"

# URLs
LOGIN_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com"
CMS_CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"

# Test character to upload
TEST_CHARACTER = "guddi"  # Simple test character
TEST_CHARACTER_DISPLAY = "Guddi"

# Image file
TEST_IMAGE_PATH = os.path.join(PROCESSED_IMAGES_DIR, "characters", f"{TEST_CHARACTER}.webp")

# Timeouts
WAIT_TIMEOUT = 20


def test_upload():
    """Test upload with one character"""
    print("\n" + "="*80)
    print("TEST UPLOADER - SINGLE CHARACTER UPLOAD")
    print("="*80 + "\n")

    # Check image exists
    if not os.path.exists(TEST_IMAGE_PATH):
        print(f"[ERROR] Image not found: {TEST_IMAGE_PATH}")
        print(f"[ERROR] Available images: {os.listdir(os.path.join(PROCESSED_IMAGES_DIR, 'characters'))}")
        return False

    file_size_kb = os.path.getsize(TEST_IMAGE_PATH) / 1024
    print(f"[OK] Found image: {TEST_CHARACTER}.jpg ({file_size_kb:.1f}KB)")
    print(f"[*] Will upload to: {TEST_CHARACTER_DISPLAY}\n")

    # Initialize driver
    print("[*] Initializing Chrome WebDriver...")
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    try:
        driver = webdriver.Chrome(options=options)
        print("[OK] Chrome WebDriver initialized\n")
    except Exception as e:
        print(f"[ERROR] Failed to initialize WebDriver: {e}")
        print("Fix: pip install webdriver-manager")
        return False

    try:
        wait = WebDriverWait(driver, WAIT_TIMEOUT)

        # Step 1: Navigate to login
        print("[Step 1/5] Navigating to login page...")
        driver.get(LOGIN_URL)
        time.sleep(2)
        print("[OK] Login page loaded\n")

        # Step 2: Login
        print("[Step 2/5] Logging in automatically...")

        # Find username input (uses id='username')
        print("  [*] Finding username input...")
        username_input = wait.until(EC.presence_of_element_located((By.ID, "username")))
        username_input.clear()
        username_input.send_keys(CMS_EMAIL)
        print(f"  [OK] Username entered: {CMS_EMAIL}")
        time.sleep(1)

        # Find password input (uses id='password')
        print("  [*] Finding password input...")
        password_input = driver.find_element(By.ID, "password")
        password_input.clear()
        password_input.send_keys(CMS_PASSWORD)
        print(f"  [OK] Password entered")
        time.sleep(1)

        # Click login button
        print("  [*] Finding login button...")
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        print(f"  [OK] Login button clicked")
        time.sleep(3)

        # Wait for dashboard
        print("  [*] Waiting for dashboard to load...")
        wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/playlists')]")))
        print("[OK] Login successful!\n")

        # Step 3: Navigate to categories
        print("[Step 3/5] Navigating to categories...")
        driver.get(CMS_CATEGORIES_URL)
        time.sleep(3)
        print("[OK] Categories page loaded\n")

        # Step 4: Search and find character
        print(f"[Step 4/5] Searching for '{TEST_CHARACTER_DISPLAY}'...")
        search_box = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']")))
        search_box.clear()
        search_box.send_keys(TEST_CHARACTER_DISPLAY)
        time.sleep(2)
        print(f"[OK] Searched for: {TEST_CHARACTER_DISPLAY}\n")

        # Step 5: Click edit and upload
        print(f"[Step 5/5] Uploading image...")

        # Find edit button
        edit_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]")))
        edit_button.click()
        print(f"  [OK] Edit button clicked")
        time.sleep(3)

        # Find file input and upload
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        print(f"  [*] Found {len(file_inputs)} file input field(s)")

        if len(file_inputs) == 0:
            print(f"  [ERROR] No file input fields found!")
            print(f"  [HINT] Check if the page structure has changed")
            return False

        abs_path = os.path.abspath(TEST_IMAGE_PATH)

        # Upload to first field
        try:
            file_inputs[0].send_keys(abs_path)
            print(f"  [OK] Uploaded to field 1")
            time.sleep(2)
        except Exception as e:
            print(f"  [ERROR] Upload to field 1 failed: {e}")

        # Upload to second field if exists
        if len(file_inputs) > 1:
            try:
                file_inputs[1].send_keys(abs_path)
                print(f"  [OK] Uploaded to field 2")
                time.sleep(2)
            except Exception as e:
                print(f"  [WARN] Upload to field 2 failed: {e}")

        # Save
        print(f"  [*] Looking for save button...")
        save_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Save')]")
        save_button.click()
        print(f"  [OK] Save button clicked")
        time.sleep(3)

        print("\n" + "="*80)
        print("[SUCCESS] TEST UPLOAD COMPLETE!")
        print("="*80 + "\n")

        print("What happened:")
        print(f"  ✓ Logged in automatically")
        print(f"  ✓ Navigated to categories")
        print(f"  ✓ Searched for '{TEST_CHARACTER_DISPLAY}'")
        print(f"  ✓ Clicked Edit")
        print(f"  ✓ Uploaded image from: {TEST_IMAGE_PATH}")
        print(f"  ✓ Clicked Save")

        print("\nIf you see this message, the automation works!")
        print("Ready to run the full uploader with all images.\n")

        input("Press ENTER to close browser...")
        return True

    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        input("\nPress ENTER to close browser...")
        driver.quit()
        print("[OK] Browser closed")


if __name__ == "__main__":
    success = test_upload()

    if success:
        print("\n" + "="*80)
        print("NEXT: Run full uploader with:")
        print("  python cms_auto_uploader.py")
        print("="*80)
    else:
        print("\n[ERROR] Test failed. Fix issues above before running full uploader.")
