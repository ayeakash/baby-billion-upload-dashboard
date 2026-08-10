"""
Automated CMS Image Uploader
Logs into CMS and uploads images to playlists and categories
"""

import os
import json
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# Configuration
BASE_DIR = r"C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard"
PROCESSED_IMAGES_DIR = os.path.join(BASE_DIR, "processed_images")
MATCHES_FILE = os.path.join(PROCESSED_IMAGES_DIR, "image_matches.json")

CMS_BASE_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms"
PLAYLISTS_URL = f"{CMS_BASE_URL}/playlists"
CATEGORIES_URL = f"{CMS_BASE_URL}/categories"
LOGIN_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com"

# Credentials
CMS_EMAIL = "Intern@babybillion.in"
CMS_PASSWORD = "57zQfDqS8ZN8bR2"

# Timeouts
WAIT_TIMEOUT = 20
SHORT_WAIT = 5

class CMSUploader:
    def __init__(self, headless=False):
        """Initialize the uploader with Chrome WebDriver"""
        self.driver = None
        self.wait = None
        self.headless = headless
        self.upload_log = []
        self.init_driver()

    def init_driver(self):
        """Initialize Chrome WebDriver"""
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")

        try:
            self.driver = webdriver.Chrome(options=options)
            self.wait = WebDriverWait(self.driver, WAIT_TIMEOUT)
            print("[OK] Chrome WebDriver initialized")
        except Exception as e:
            print(f"[ERROR] Failed to initialize WebDriver: {str(e)}")
            print("Make sure ChromeDriver is installed and in PATH")
            raise

    def load_matches(self):
        """Load image matches from JSON file"""
        try:
            with open(MATCHES_FILE, 'r') as f:
                matches = json.load(f)
            print(f"[OK] Loaded {len(matches)} match categories")
            return matches
        except FileNotFoundError:
            print(f"[ERROR] Matches file not found: {MATCHES_FILE}")
            return None
        except Exception as e:
            print(f"[ERROR] Failed to load matches: {str(e)}")
            return None

    def navigate_to_url(self, url):
        """Navigate to a URL"""
        try:
            print(f"[*] Navigating to {url}")
            self.driver.get(url)
            time.sleep(2)
            return True
        except Exception as e:
            print(f"[ERROR] Navigation failed: {str(e)}")
            return False

    def auto_login(self):
        """Automatically log in with credentials"""
        try:
            print("\n[*] Starting auto-login process...")
            self.navigate_to_url(LOGIN_URL)

            # Wait for login form
            print("[*] Looking for email input...")
            email_input = self.wait_for_element(By.CSS_SELECTOR, "input[type='email']")
            if not email_input:
                email_input = self.wait_for_element(By.CSS_SELECTOR, "input[name='email']")
            if not email_input:
                email_input = self.wait_for_element(By.XPATH, "//input[@type='email' or @name='email']")

            if email_input:
                email_input.clear()
                email_input.send_keys(CMS_EMAIL)
                print(f"[OK] Email entered: {CMS_EMAIL}")
                time.sleep(1)
            else:
                print("[ERROR] Could not find email input field")
                return False

            # Find password input
            print("[*] Looking for password input...")
            password_input = self.wait_for_element(By.CSS_SELECTOR, "input[type='password']")
            if not password_input:
                password_input = self.wait_for_element(By.CSS_SELECTOR, "input[name='password']")
            if not password_input:
                password_input = self.wait_for_element(By.XPATH, "//input[@type='password' or @name='password']")

            if password_input:
                password_input.clear()
                password_input.send_keys(CMS_PASSWORD)
                print("[OK] Password entered")
                time.sleep(1)
            else:
                print("[ERROR] Could not find password input field")
                return False

            # Find and click login button
            print("[*] Looking for login button...")
            login_button = None

            # Try different button selectors
            button_selectors = [
                "button[type='submit']",
                "//button[contains(text(), 'Login')]",
                "//button[contains(text(), 'Sign In')]",
                "//button[contains(text(), 'Log In')]",
                ".login-button",
                "[data-testid='login-button']"
            ]

            for selector in button_selectors:
                try:
                    if selector.startswith("//"):
                        login_button = self.driver.find_element(By.XPATH, selector)
                    else:
                        login_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if login_button:
                        break
                except:
                    continue

            if login_button:
                login_button.click()
                print("[OK] Login button clicked")
                time.sleep(3)
            else:
                print("[ERROR] Could not find login button")
                return False

            # Wait for dashboard to load
            print("[*] Waiting for dashboard to load...")
            for i in range(30):
                try:
                    self.driver.find_element(By.XPATH, "//a[contains(@href, '/playlists')]")
                    print("[OK] Dashboard loaded successfully!")
                    time.sleep(2)
                    return True
                except:
                    time.sleep(1)
                    if i % 5 == 0:
                        print(f"[*] Still loading... ({i}s)")

            print("[ERROR] Dashboard did not load in time")
            return False

        except Exception as e:
            print(f"[ERROR] Login failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def wait_for_element(self, by, value, timeout=WAIT_TIMEOUT):
        """Wait for an element to be present"""
        try:
            element = self.wait.until(EC.presence_of_element_located((by, value)))
            return element
        except:
            return None

    def click_element(self, by, value):
        """Click an element with wait"""
        try:
            element = self.wait.until(EC.element_to_be_clickable((by, value)))
            element.click()
            return True
        except Exception as e:
            print(f"[ERROR] Could not click element: {str(e)}")
            return False

    def upload_file(self, file_path, field_selector):
        """Upload a file to an input field"""
        try:
            if not os.path.exists(file_path):
                print(f"[ERROR] File not found: {file_path}")
                return False

            # Convert to absolute path
            abs_path = os.path.abspath(file_path)

            # Find the file input element
            input_element = self.driver.find_element(By.CSS_SELECTOR, field_selector)

            # Send the file path to the input
            input_element.send_keys(abs_path)

            print(f"[OK] File uploaded: {os.path.basename(file_path)}")
            time.sleep(2)
            return True
        except Exception as e:
            print(f"[ERROR] Upload failed: {str(e)}")
            return False

    def save_changes(self):
        """Click save button"""
        try:
            # Try different save button selectors
            selectors = [
                "button:contains('Save')",
                "//button[contains(text(), 'Save')]",
                "[data-testid='save-button']",
                ".save-button",
                "button.btn-primary:last-of-type"
            ]

            for selector in selectors:
                try:
                    if selector.startswith("//"):
                        button = self.driver.find_element(By.XPATH, selector)
                    else:
                        button = self.driver.find_element(By.CSS_SELECTOR, selector)

                    if button:
                        button.click()
                        print("[OK] Save clicked")
                        time.sleep(3)
                        return True
                except:
                    continue

            print("[WARN] Could not find save button - may need manual save")
            return False
        except Exception as e:
            print(f"[ERROR] Save failed: {str(e)}")
            return False

    def upload_to_playlists(self, matches):
        """Upload images to playlists"""
        if 'playlists' not in matches:
            print("[WARN] No playlist matches found")
            return

        print("\n" + "="*80)
        print("UPLOADING PLAYLISTS")
        print("="*80)

        playlist_matches = matches['playlists']
        self.navigate_to_url(PLAYLISTS_URL)

        for img_name, match_info in sorted(playlist_matches.items()):
            if not match_info['display_name']:
                print(f"[SKIP] {img_name} - no match")
                continue

            display_name = match_info['display_name']
            image_path = os.path.join(PROCESSED_IMAGES_DIR, "playlists", f"{img_name}.jpg")

            print(f"\nUploading: {display_name}")
            print(f"  Image: {os.path.basename(image_path)}")

            # Search for the playlist
            search_box = self.wait_for_element(By.CSS_SELECTOR, "input[placeholder*='Search']")
            if search_box:
                search_box.clear()
                search_box.send_keys(display_name)
                time.sleep(2)

            # Click edit button (adjust selector based on actual CMS structure)
            edit_clicked = self.click_element(By.XPATH, f"//button[contains(text(), 'Edit')]")
            if not edit_clicked:
                print(f"[WARN] Could not find edit button for {display_name}")
                continue

            time.sleep(3)

            # Upload to both thumbnail fields
            thumbnail_selectors = [
                "input[type='file'][accept*='image']",
                ".thumbnail-upload input[type='file']",
                "input[placeholder*='Thumbnail']"
            ]

            uploaded_count = 0
            for selector in thumbnail_selectors:
                try:
                    if self.upload_file(image_path, selector):
                        uploaded_count += 1
                except:
                    continue

            if uploaded_count >= 2:
                self.save_changes()
                self.upload_log.append({
                    'type': 'playlist',
                    'name': display_name,
                    'image': os.path.basename(image_path),
                    'status': 'uploaded'
                })
                print(f"[OK] {display_name} uploaded")
            else:
                print(f"[WARN] Could not upload both thumbnails for {display_name}")
                self.upload_log.append({
                    'type': 'playlist',
                    'name': display_name,
                    'image': os.path.basename(image_path),
                    'status': 'partial'
                })

            # Go back to playlist list
            self.driver.back()
            time.sleep(2)

    def upload_to_categories(self, matches):
        """Upload images to categories"""
        if 'categories' not in matches:
            print("[WARN] No category matches found")
            return

        print("\n" + "="*80)
        print("UPLOADING CATEGORIES")
        print("="*80)

        category_matches = matches['categories']
        self.navigate_to_url(CATEGORIES_URL)

        for img_name, match_info in sorted(category_matches.items()):
            if not match_info['display_name']:
                print(f"[SKIP] {img_name} - no match")
                continue

            display_name = match_info['display_name']
            image_path = os.path.join(PROCESSED_IMAGES_DIR, "categories", f"{img_name}.jpg")

            print(f"\nUploading: {display_name}")
            print(f"  Image: {os.path.basename(image_path)}")

            # Search for the category
            search_box = self.wait_for_element(By.CSS_SELECTOR, "input[placeholder*='Search']")
            if search_box:
                search_box.clear()
                search_box.send_keys(display_name)
                time.sleep(2)

            # Click edit button
            edit_clicked = self.click_element(By.XPATH, f"//button[contains(text(), 'Edit')]")
            if not edit_clicked:
                print(f"[WARN] Could not find edit button for {display_name}")
                continue

            time.sleep(3)

            # Upload to both thumbnail fields
            thumbnail_selectors = [
                "input[type='file'][accept*='image']",
                ".thumbnail-upload input[type='file']",
                "input[placeholder*='Thumbnail']"
            ]

            uploaded_count = 0
            for selector in thumbnail_selectors:
                try:
                    if self.upload_file(image_path, selector):
                        uploaded_count += 1
                except:
                    continue

            if uploaded_count >= 2:
                self.save_changes()
                self.upload_log.append({
                    'type': 'category',
                    'name': display_name,
                    'image': os.path.basename(image_path),
                    'status': 'uploaded'
                })
                print(f"[OK] {display_name} uploaded")
            else:
                print(f"[WARN] Could not upload both thumbnails for {display_name}")
                self.upload_log.append({
                    'type': 'category',
                    'name': display_name,
                    'image': os.path.basename(image_path),
                    'status': 'partial'
                })

            # Go back to category list
            self.driver.back()
            time.sleep(2)

    def save_upload_log(self):
        """Save upload log to file"""
        log_file = os.path.join(PROCESSED_IMAGES_DIR, "UPLOAD_LOG.json")
        try:
            with open(log_file, 'w') as f:
                json.dump(self.upload_log, f, indent=2)
            print(f"\n[OK] Upload log saved to {log_file}")
        except Exception as e:
            print(f"[ERROR] Failed to save upload log: {str(e)}")

    def close(self):
        """Close the WebDriver"""
        if self.driver:
            self.driver.quit()
            print("[OK] Browser closed")

    def run(self):
        """Run the uploader"""
        try:
            print("\n" + "="*80)
            print("BABY BILLION CMS AUTO UPLOADER")
            print("="*80 + "\n")

            # Load matches
            matches = self.load_matches()
            if not matches:
                print("[ERROR] Could not load image matches")
                return

            print("[*] Starting automatic login...\n")

            # Auto-login
            logged_in = self.auto_login()

            if not logged_in:
                print("[ERROR] Auto-login failed!")
                return

            print("[OK] Login successful! Starting uploads...\n")

            # Upload images
            self.upload_to_playlists(matches)
            self.upload_to_categories(matches)

            # Save log
            self.save_upload_log()

            print("\n" + "="*80)
            print("UPLOAD COMPLETE")
            print("="*80)
            print(f"\nTotal uploads: {len(self.upload_log)}")

        except KeyboardInterrupt:
            print("\n[WARN] Upload cancelled by user")
        except Exception as e:
            print(f"\n[ERROR] Uploader error: {str(e)}")
        finally:
            self.close()


def main():
    """Main function"""
    uploader = CMSUploader(headless=False)  # Set to True for headless mode
    uploader.run()


if __name__ == "__main__":
    main()
