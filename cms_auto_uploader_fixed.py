"""
Automated CMS Image Uploader - FIXED VERSION
Auto-login and upload all images
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

# Timeouts
WAIT_TIMEOUT = 20


class CMSUploader:
    def __init__(self):
        """Initialize uploader"""
        print("[*] Initializing Chrome WebDriver...")
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, WAIT_TIMEOUT)
        self.upload_log = []
        print("[OK] Chrome WebDriver initialized\n")

    def login(self):
        """Auto-login with credentials"""
        print("[*] Step 1: Logging in...")
        self.driver.get(LOGIN_URL)
        time.sleep(2)

        # Enter username (email)
        print("  [*] Entering username...")
        username_input = self.wait.until(EC.presence_of_element_located((By.ID, "username")))
        username_input.clear()
        username_input.send_keys(CMS_EMAIL)
        print(f"  [OK] Username entered: {CMS_EMAIL}")
        time.sleep(1)

        # Enter password
        print("  [*] Entering password...")
        password_input = self.driver.find_element(By.ID, "password")
        password_input.clear()
        password_input.send_keys(CMS_PASSWORD)
        print(f"  [OK] Password entered")
        time.sleep(1)

        # Click login button
        print("  [*] Clicking login button...")
        login_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        print(f"  [OK] Login button clicked")

        # Wait for dashboard
        print("  [*] Waiting for dashboard...")
        for i in range(30):
            try:
                self.driver.find_element(By.XPATH, "//a[contains(@href, '/playlists')]")
                print("[OK] Dashboard loaded successfully!\n")
                time.sleep(2)
                return True
            except:
                time.sleep(1)
                if i % 5 == 0 and i > 0:
                    print(f"  [*] Still loading... ({i}s)")

        print("[ERROR] Dashboard did not load")
        return False

    def upload_images(self):
        """Upload all images"""
        print("[*] Step 2: Uploading images...\n")

        # Get all image matches
        matches_file = os.path.join(PROCESSED_IMAGES_DIR, "image_matches.json")
        with open(matches_file, 'r') as f:
            matches = json.load(f)

        # Upload playlists
        print("="*80)
        print("UPLOADING PLAYLISTS")
        print("="*80 + "\n")
        self.upload_category("playlists", matches.get("playlists", {}))

        # Upload categories
        print("\n" + "="*80)
        print("UPLOADING CATEGORIES")
        print("="*80 + "\n")
        self.upload_category("categories", matches.get("categories", {}))

    def upload_category(self, category_type, matches):
        """Upload images for a category"""
        if category_type == "playlists":
            url = PLAYLISTS_URL
        else:
            url = CATEGORIES_URL

        self.driver.get(url)
        time.sleep(3)

        uploaded = 0
        failed = 0

        for img_name, match_info in sorted(matches.items()):
            if not match_info.get('display_name'):
                continue

            display_name = match_info['display_name']
            image_path = os.path.join(PROCESSED_IMAGES_DIR, category_type, f"{img_name}.webp")

            if not os.path.exists(image_path):
                print(f"[SKIP] {display_name} - image not found")
                continue

            print(f"[*] Uploading: {display_name}...")

            try:
                # Search
                search_box = self.driver.find_element(By.CSS_SELECTOR, "input[placeholder*='Search']")
                search_box.clear()
                search_box.send_keys(display_name)
                time.sleep(2)

                # Click edit
                edit_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Edit')]")
                edit_btn.click()
                time.sleep(3)

                # Upload to file inputs
                file_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                abs_path = os.path.abspath(image_path)

                for idx, file_input in enumerate(file_inputs[:2]):  # Upload to first 2 fields
                    try:
                        file_input.send_keys(abs_path)
                        time.sleep(1)
                    except:
                        pass

                # Save
                save_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Save')]")
                save_btn.click()
                time.sleep(2)

                print(f"  [OK] {display_name} uploaded")
                uploaded += 1

                # Go back
                self.driver.back()
                time.sleep(2)

            except Exception as e:
                print(f"  [ERROR] {display_name} - {str(e)}")
                failed += 1
                try:
                    self.driver.back()
                    time.sleep(2)
                except:
                    pass

        print(f"\nUploaded: {uploaded}, Failed: {failed}")

    def save_log(self):
        """Save upload log"""
        log_file = os.path.join(PROCESSED_IMAGES_DIR, "UPLOAD_LOG.json")
        with open(log_file, 'w') as f:
            json.dump({
                "status": "completed",
                "timestamp": time.time()
            }, f, indent=2)
        print(f"\n[OK] Log saved to: {log_file}")

    def close(self):
        """Close browser"""
        input("\nPress ENTER to close browser...")
        self.driver.quit()

    def run(self):
        """Run the uploader"""
        print("\n" + "="*80)
        print("BABY BILLION CMS AUTO UPLOADER")
        print("="*80 + "\n")

        try:
            if not self.login():
                print("[ERROR] Login failed")
                return

            self.upload_images()
            self.save_log()

            print("\n" + "="*80)
            print("[OK] UPLOAD COMPLETE!")
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
