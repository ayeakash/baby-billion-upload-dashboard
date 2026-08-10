"""
Upload to Home View using JavaScript to set file input directly
"""

import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

BASE_DIR = r"C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard"
PROCESSED_IMAGES_DIR = os.path.join(BASE_DIR, "processed_images_34")

CMS_EMAIL = "Intern@babybillion.in"
CMS_PASSWORD = "57zQfDqS8ZN8bR2"

LOGIN_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com"
CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"

WAIT_TIMEOUT = 30

# Test with just a few items first
TEST_ITEMS = {
    'characters': {
        'golu': 'Golu',
        'guddi': 'Guddi',
    },
    'categories': {
        'ABC': 'Learn Your ABC',
        'about_india': 'About India',
    }
}

class CMSUploader:
    def __init__(self):
        self.driver = None
        self.wait = None
        self.upload_count = 0

    def init_driver(self):
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--start-maximized")
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, WAIT_TIMEOUT)

    def close_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None

    def login(self):
        self.driver.get(LOGIN_URL)
        time.sleep(3)
        username_input = self.wait.until(EC.presence_of_element_located((By.ID, "username")))
        username_input.clear()
        username_input.send_keys(CMS_EMAIL)
        time.sleep(1)
        password_input = self.driver.find_element(By.ID, "password")
        password_input.clear()
        password_input.send_keys(CMS_PASSWORD)
        time.sleep(1)
        login_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        for i in range(30):
            try:
                self.driver.find_element(By.XPATH, "//a[contains(@href, '/playlists')]")
                time.sleep(2)
                return True
            except:
                time.sleep(1)
        return False

    def upload_to_homeview(self, real_name, img_filename, img_type):
        """Upload to Home View using JavaScript file setting"""
        try:
            self.driver.get(CATEGORIES_URL)
            time.sleep(4)

            # Search
            search_box = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']"))
            )
            search_box.clear()
            search_box.send_keys(real_name)
            time.sleep(3)

            # Click Edit
            edit_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]"))
            )
            edit_button.click()
            time.sleep(4)

            # Check if file exists
            image_path = os.path.join(PROCESSED_IMAGES_DIR, img_type, f"{img_filename}.webp")
            if not os.path.exists(image_path):
                return False

            abs_path = os.path.abspath(image_path)

            # Get home view input element
            home_input = self.wait.until(
                EC.presence_of_element_located((By.ID, "cp-thumb-home"))
            )

            # Check if it's visible/enabled
            print(f"    DEBUG: Input visible={home_input.is_displayed()}, enabled={home_input.is_enabled()}")

            # Try method 1: send_keys
            try:
                home_input.send_keys(abs_path)
                time.sleep(2)
                print(f"    DEBUG: send_keys worked")
            except Exception as e:
                print(f"    DEBUG: send_keys failed: {e}")

                # Try method 2: JavaScript to set file
                try:
                    # This won't work due to security, but let's see what happens
                    self.driver.execute_script(f"arguments[0].value = '{abs_path}';", home_input)
                    time.sleep(2)
                    print(f"    DEBUG: JS setValue worked")
                except Exception as e2:
                    print(f"    DEBUG: JS setValue failed: {e2}")
                    return False

            # Click Save
            save_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Save')]")
            save_button.click()
            time.sleep(3)
            self.upload_count += 1
            return True

        except Exception as e:
            print(f"    DEBUG: Exception: {e}")
            return False

    def run(self):
        print("\n" + "="*80)
        print("TESTING HOME VIEW UPLOAD WITH JAVASCRIPT")
        print("="*80 + "\n")

        self.init_driver()
        if not self.login():
            print("[ERROR] Login failed")
            return

        # Test characters
        print("CHARACTERS (TEST):")
        for img_file, real_name in sorted(TEST_ITEMS['characters'].items()):
            print(f"  Testing {real_name}...")
            if self.upload_to_homeview(real_name, img_file, "characters"):
                print(f"    [OK] {real_name}")
            else:
                print(f"    [FAIL] {real_name}")

        # Test categories
        print("\nCATEGORIES (TEST):")
        for img_file, real_name in sorted(TEST_ITEMS['categories'].items()):
            print(f"  Testing {real_name}...")
            if self.upload_to_homeview(real_name, img_file, "categories"):
                print(f"    [OK] {real_name}")
            else:
                print(f"    [FAIL] {real_name}")

        self.close_driver()

        print("\n" + "="*80)
        print(f"TEST COMPLETE: {self.upload_count} items uploaded")
        print("="*80 + "\n")


if __name__ == "__main__":
    uploader = CMSUploader()
    uploader.run()
