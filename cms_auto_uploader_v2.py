"""
CMS Auto Uploader v2 - FIXED
Better page navigation and wait handling
"""

import os
import json
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
PLAYLISTS_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/playlists"
CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"

# Already uploaded in previous runs - skip these
ALREADY_UPLOADED = set()  # Upload everything from fresh with updated 1:1 category images

# Timeouts
WAIT_TIMEOUT = 20


class CMSUploader:
    def __init__(self):
        """Initialize uploader"""
        print("[*] Initializing Chrome WebDriver...")
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--start-maximized")

        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, WAIT_TIMEOUT)
        self.upload_count = 0
        print("[OK] Chrome WebDriver initialized\n")

    def login(self):
        """Auto-login with credentials"""
        print("[*] Step 1: Logging in...")
        self.driver.get(LOGIN_URL)
        time.sleep(3)

        # Enter username
        print("  [*] Entering username...")
        username_input = self.wait.until(EC.presence_of_element_located((By.ID, "username")))
        username_input.clear()
        username_input.send_keys(CMS_EMAIL)
        print(f"  [OK] Username entered")
        time.sleep(1)

        # Enter password
        print("  [*] Entering password...")
        password_input = self.driver.find_element(By.ID, "password")
        password_input.clear()
        password_input.send_keys(CMS_PASSWORD)
        print(f"  [OK] Password entered")
        time.sleep(1)

        # Click login
        print("  [*] Clicking login...")
        login_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        print(f"  [OK] Login button clicked")

        # Wait for dashboard
        print("  [*] Waiting for dashboard...")
        for i in range(30):
            try:
                self.driver.find_element(By.XPATH, "//a[contains(@href, '/playlists')]")
                print("[OK] Logged in successfully!\n")
                time.sleep(2)
                return True
            except:
                time.sleep(1)

        print("[ERROR] Login timeout")
        return False

    def upload_single(self, category_type, display_name, img_name):
        """Upload a single image - fresh page load each time"""
        try:
            # Navigate to fresh list page
            if category_type == "playlists":
                url = PLAYLISTS_URL
            else:
                url = CATEGORIES_URL

            print(f"[*] Loading {category_type} page...")
            self.driver.get(url)
            time.sleep(4)  # Wait for page to load

            # Find and use search
            print(f"  [*] Searching for '{display_name}'...")
            search_box = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']"))
            )
            search_box.clear()
            search_box.send_keys(display_name)
            time.sleep(3)  # Wait for search results

            # Click edit
            print(f"  [*] Clicking edit...")
            edit_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]"))
            )
            edit_button.click()
            time.sleep(4)  # Wait for edit page to load

            # Find image path
            image_path = os.path.join(PROCESSED_IMAGES_DIR, category_type, f"{img_name}.webp")
            if not os.path.exists(image_path):
                print(f"  [SKIP] Image not found: {image_path}")
                return False

            # Upload files
            print(f"  [*] Uploading image...")
            file_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")

            if not file_inputs:
                print(f"  [ERROR] No file inputs found")
                return False

            abs_path = os.path.abspath(image_path)
            uploaded = 0

            # Upload to first two fields
            for idx, file_input in enumerate(file_inputs[:2]):
                try:
                    file_input.send_keys(abs_path)
                    uploaded += 1
                    print(f"  [OK] Uploaded to field {idx + 1}")
                    time.sleep(1)
                except Exception as e:
                    print(f"  [WARN] Field {idx + 1} failed: {e}")

            if uploaded == 0:
                print(f"  [ERROR] Could not upload to any field")
                return False

            # Save
            print(f"  [*] Saving...")
            try:
                save_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Save')]")
                save_button.click()
                time.sleep(3)
                print(f"[OK] {display_name} uploaded\n")
                self.upload_count += 1
                return True
            except:
                print(f"  [WARN] Could not click save")
                return False

        except Exception as e:
            print(f"[ERROR] {display_name} - {str(e)}\n")
            return False

    def upload_all(self):
        """Upload all images"""
        print("[*] Step 2: Uploading images...\n")

        # Load matches
        matches_file = os.path.join(PROCESSED_IMAGES_DIR, "image_matches.json")
        with open(matches_file, 'r') as f:
            matches = json.load(f)

        # Upload playlists
        print("="*80)
        print("UPLOADING PLAYLISTS")
        print("="*80 + "\n")

        for img_name, match_info in sorted(matches.get("playlists", {}).items()):
            if not match_info.get('display_name'):
                continue
            if img_name.lower() in ALREADY_UPLOADED:
                print(f"[SKIP] {match_info['display_name']} (already uploaded)")
                continue
            self.upload_single("playlists", match_info['display_name'], img_name)

        # Upload categories
        print("="*80)
        print("UPLOADING CATEGORIES")
        print("="*80 + "\n")

        for img_name, match_info in sorted(matches.get("categories", {}).items()):
            if not match_info.get('display_name'):
                continue
            if img_name.lower() in ALREADY_UPLOADED:
                print(f"[SKIP] {match_info['display_name']} (already uploaded)")
                continue
            self.upload_single("categories", match_info['display_name'], img_name)

    def close(self):
        """Close browser"""
        input("\nPress ENTER to close browser...")
        self.driver.quit()

    def run(self):
        """Run the uploader"""
        print("\n" + "="*80)
        print("BABY BILLION CMS AUTO UPLOADER V2")
        print("="*80 + "\n")

        try:
            if not self.login():
                print("[ERROR] Login failed")
                return

            self.upload_all()

            print("\n" + "="*80)
            print(f"[OK] UPLOAD COMPLETE - {self.upload_count} items uploaded")
            print("="*80)

        except Exception as e:
            print(f"\n[ERROR] {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.close()


if __name__ == "__main__":
    uploader = CMSUploader()
    uploader.run()
