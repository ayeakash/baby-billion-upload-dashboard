"""
Update 1:1 category images - List View Only
"""

import os
import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

BASE_DIR = r"C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard"
PROCESSED_IMAGES_DIR = os.path.join(BASE_DIR, "processed_images")

CMS_EMAIL = "Intern@babybillion.in"
CMS_PASSWORD = "57zQfDqS8ZN8bR2"

LOGIN_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com"
CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"

WAIT_TIMEOUT = 30

class CMSUploader:
    def __init__(self):
        self.driver = None
        self.wait = None
        self.upload_count = 0
        self.failed_items = []

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
            self.wait = None

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

    def upload_single(self, display_name, img_name):
        try:
            self.driver.get(CATEGORIES_URL)
            time.sleep(4)
            search_box = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']"))
            )
            search_box.clear()
            search_box.send_keys(display_name)
            time.sleep(3)
            edit_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]"))
            )
            edit_button.click()
            time.sleep(4)

            image_path = os.path.join(PROCESSED_IMAGES_DIR, "categories", f"{img_name}.webp")
            if not os.path.exists(image_path):
                return False

            file_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if not file_inputs:
                return False

            abs_path = os.path.abspath(image_path)
            uploaded = 0
            for file_input in file_inputs[:2]:
                try:
                    file_input.send_keys(abs_path)
                    uploaded += 1
                    time.sleep(1)
                except:
                    pass

            if uploaded == 0:
                return False

            save_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Save')]")
            save_button.click()
            time.sleep(3)
            self.upload_count += 1
            return True

        except Exception as e:
            self.failed_items.append(display_name)
            return False

    def run(self):
        print("\n" + "="*80)
        print("UPDATING 1:1 CATEGORY IMAGES - LIST VIEW")
        print("="*80 + "\n")

        self.init_driver()
        if not self.login():
            print("[ERROR] Login failed")
            return

        matches_file = os.path.join(PROCESSED_IMAGES_DIR, "image_matches.json")
        with open(matches_file, 'r') as f:
            matches = json.load(f)

        print("UPDATING CATEGORIES:")
        for img_name, match_info in sorted(matches.get("categories", {}).items()):
            if match_info.get('display_name'):
                if self.upload_single(match_info['display_name'], img_name):
                    print(f"  ✓ {match_info['display_name']}")
                else:
                    print(f"  ✗ {match_info['display_name']}")

        self.close_driver()

        print("\n" + "="*80)
        print(f"COMPLETE: {self.upload_count} items updated")
        if self.failed_items:
            print(f"Failed: {len(self.failed_items)}")
        print("="*80 + "\n")


if __name__ == "__main__":
    uploader = CMSUploader()
    uploader.run()
