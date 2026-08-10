"""
CMS Auto Uploader - RESUME
Uploads only remaining categories (skips playlists and Alphabets)
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
CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"

# Already uploaded - skip these
ALREADY_UPLOADED = {
    # Playlists (9 successfully uploaded)
    "animals", "around_us", "geography", "hindi_basics", "math",
    "nature", "our_world", "science", "stories",

    # Categories (14 successfully uploaded)
    "about_india", "birds", "body_parts", "english_speaking",
    "farm_animals", "fractions", "greater_and_lesser", "knowledge",
    "prepositions", "seasons", "time", "varnmala", "vyanjan", "words"
}

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

    def upload_single(self, display_name, img_name):
        """Upload a single category - fresh page load"""
        try:
            # Navigate to fresh category page
            print(f"[*] Loading categories page...")
            self.driver.get(CATEGORIES_URL)
            time.sleep(4)

            # Find and use search
            print(f"  [*] Searching for '{display_name}'...")
            search_box = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']"))
            )
            search_box.clear()
            search_box.send_keys(display_name)
            time.sleep(3)

            # Click edit
            print(f"  [*] Clicking edit...")
            edit_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]"))
            )
            edit_button.click()
            time.sleep(4)

            # Find image path
            image_path = os.path.join(PROCESSED_IMAGES_DIR, "categories", f"{img_name}.webp")
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

    def upload_remaining(self):
        """Upload remaining playlists and categories"""
        print("[*] Step 2: Uploading remaining items...\n")

        # Load matches
        matches_file = os.path.join(PROCESSED_IMAGES_DIR, "image_matches.json")
        with open(matches_file, 'r') as f:
            matches = json.load(f)

        # Try uploading remaining playlists
        print("="*80)
        print("UPLOADING REMAINING PLAYLISTS")
        print("="*80 + "\n")

        skipped_playlists = 0
        for img_name, match_info in sorted(matches.get("playlists", {}).items()):
            if not match_info.get('display_name'):
                continue

            # Skip already uploaded
            if img_name.lower() in ALREADY_UPLOADED:
                print(f"[SKIP] {match_info['display_name']} (already uploaded)")
                skipped_playlists += 1
                continue

            # Use playlist URL for playlists
            try:
                print(f"[*] Loading playlists page...")
                self.driver.get(CATEGORIES_URL.replace('categories', 'playlists'))
                time.sleep(4)

                print(f"  [*] Searching for '{match_info['display_name']}'...")
                search_box = self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']"))
                )
                search_box.clear()
                search_box.send_keys(match_info['display_name'])
                time.sleep(3)

                print(f"  [*] Clicking edit...")
                edit_button = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]"))
                )
                edit_button.click()
                time.sleep(4)

                image_path = os.path.join(PROCESSED_IMAGES_DIR, "playlists", f"{img_name}.webp")
                if not os.path.exists(image_path):
                    print(f"  [SKIP] Image not found: {image_path}")
                    continue

                file_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                if not file_inputs:
                    print(f"  [ERROR] No file inputs found")
                    continue

                abs_path = os.path.abspath(image_path)
                for idx, file_input in enumerate(file_inputs[:2]):
                    try:
                        file_input.send_keys(abs_path)
                        time.sleep(1)
                    except:
                        pass

                save_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Save')]")
                save_button.click()
                time.sleep(3)
                print(f"[OK] {match_info['display_name']} uploaded\n")
                self.upload_count += 1
            except Exception as e:
                print(f"[ERROR] {match_info['display_name']} - {str(e)}\n")

        print("="*80)
        print("UPLOADING REMAINING CATEGORIES")
        print("="*80 + "\n")

        skipped_categories = 0
        for img_name, match_info in sorted(matches.get("categories", {}).items()):
            if not match_info.get('display_name'):
                continue

            # Skip already uploaded
            if img_name.lower() in ALREADY_UPLOADED:
                print(f"[SKIP] {match_info['display_name']} (already uploaded)")
                skipped_categories += 1
                continue

            self.upload_single(match_info['display_name'], img_name)

        print(f"\nSkipped playlists: {skipped_playlists}")
        print(f"Skipped categories: {skipped_categories}")

    def close(self):
        """Close browser"""
        input("\nPress ENTER to close browser...")
        self.driver.quit()

    def run(self):
        """Run the uploader"""
        print("\n" + "="*80)
        print("CMS AUTO UPLOADER - RESUME MODE")
        print("="*80 + "\n")

        try:
            if not self.login():
                print("[ERROR] Login failed")
                return

            self.upload_remaining()

            print("\n" + "="*80)
            print(f"[OK] RESUME COMPLETE - {self.upload_count} items uploaded this session")
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
