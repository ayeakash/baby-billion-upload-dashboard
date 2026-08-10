"""
Upload only 100% matches that haven't been uploaded yet
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
PLAYLISTS_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/playlists"
CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"

WAIT_TIMEOUT = 30

# Already successfully uploaded
ALREADY_UPLOADED = {
    # Playlists (all 15)
    "alphabets", "animals", "around_us", "curious_kids", "english",
    "geography", "hindi_basics", "manners", "math", "nature",
    "numbers", "our_world", "rhymes", "science", "stories",

    # Characters (15 of 19)
    "arjun", "golu", "guddi", "hanuman", "krishna", "mia", "mishka",
    "priya", "shivji", "sindbad", "tara", "teja", "tenali", "veer", "zoya",

    # Categories (18 of 49)
    "ABC", "about_india", "action_words", "aladdin", "clothes",
    "colors", "community_helpers", "countries", "emotions", "english",
    "festivals", "food_items", "fractions", "fruits", "good_habits",
    "greater_and_lesser", "home_items", "knowledge"
}

class CMSUploader:
    def __init__(self):
        self.driver = None
        self.wait = None
        self.upload_count = 0
        self.failed_items = []

    def init_driver(self):
        print("[*] Initializing Chrome...")
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

    def upload_single(self, category_type, display_name, img_name):
        try:
            url = PLAYLISTS_URL if category_type == "playlists" else CATEGORIES_URL
            self.driver.get(url)
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

            image_path = os.path.join(PROCESSED_IMAGES_DIR, category_type, f"{img_name}.webp")
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
            self.failed_items.append(f"{category_type}: {display_name}")
            return False

    def run(self):
        print("\n" + "="*100)
        print("UPLOADING 100% MATCHES ONLY - LIST VIEW")
        print("="*100 + "\n")

        self.init_driver()
        if not self.login():
            print("[ERROR] Login failed")
            return

        matches_file = os.path.join(PROCESSED_IMAGES_DIR, "image_matches.json")
        with open(matches_file, 'r') as f:
            matches = json.load(f)

        # Upload characters (100% matches not yet uploaded)
        print("CHARACTERS (100% matches only):")
        for img_name, match_info in sorted(matches.get("characters", {}).items()):
            if match_info.get('display_name') and match_info.get('score') >= 0.99:
                if img_name not in ALREADY_UPLOADED:
                    if self.upload_single("characters", match_info['display_name'], img_name):
                        print(f"  ✓ {match_info['display_name']}")
                    else:
                        print(f"  ✗ {match_info['display_name']}")

        # Upload categories (100% matches not yet uploaded)
        print("\nCATEGORIES (100% matches only):")
        cat_count = 0
        for img_name, match_info in sorted(matches.get("categories", {}).items()):
            if match_info.get('display_name') and match_info.get('score') >= 0.99:
                if img_name not in ALREADY_UPLOADED:
                    cat_count += 1
                    if self.upload_single("categories", match_info['display_name'], img_name):
                        print(f"  ✓ {match_info['display_name']}")
                    else:
                        print(f"  ✗ {match_info['display_name']}")

        self.close_driver()

        print("\n" + "="*100)
        print(f"COMPLETE: {self.upload_count} items uploaded")
        if self.failed_items:
            print(f"Failed: {len(self.failed_items)} items")
            for item in self.failed_items:
                print(f"  - {item}")
        print("="*100 + "\n")


if __name__ == "__main__":
    uploader = CMSUploader()
    uploader.run()
