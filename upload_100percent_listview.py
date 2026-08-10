"""
Upload ONLY 100% matches to List View - Search by REAL category names
"""

import os
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
CHARACTERS_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"  # Characters are categories

WAIT_TIMEOUT = 30

# 100% matches only - mapped to image filenames
CATEGORIES_100PERCENT = {
    'ABC': 'Learn Your ABC',
    'about_india': 'About India',
    'action_words': 'Try These Actions',
    'aladdin': 'Aladdin',
    'clothes': 'Clothes',
    'colors': 'Learn Color names',
    'community_helpers': 'What Do They Do',
    'countries': 'Visit New Countries',
    'emotions': 'Understand Your Feelings',
    'english': 'Learn New Words',
    'festivals': 'Celebrate With Everyone',
    'food_items': 'Choose Healthy Foods',
    'fractions': 'Fractions',
    'fruits': 'Name Your Fruits',
    'good_habits': 'Practice Good Habits',
    'greater_and_lesser': 'Greater & Lesser',
    'hanuman': 'Hanuman',
    'home_items': 'Find Things Around',
    'knowledge': 'Knowledge',
    'krishna': 'Krishna',
    'mishka_and_momo': 'Mishka And Momo',
    'ms_isha': 'Shapes With Ms Isha',
    'ms_nidhi': 'Pronounce With Ms Nidhi',
    'ms_pranika': 'Maths With Ms Pranika',
    'my_body': 'Know Body Parts',
    'my_family': 'Meet Your Family',
    'opposites': 'Learn Opposite Words',
    'panchatantra': 'Panchatantra',
    'places_to_go': 'Let\'s Go Outside',
    'plants': 'Watch Plants Grow',
    'prepositions': 'Prepositions',
    'professions': 'What Do They Do',
    'safety': 'Safety',
    'shivji': 'Shivji',
    'sight_words': 'Read Simple Words',
    'simple_sentences': 'Start With Sentences',
    'sindbad': 'Sindbad',
    'space': 'Visit Outer Space',
    'sports': 'Explore Different Sports',
    'technology': 'Knowledge',
    'tenali': 'Tenali',
    'time': 'Time',
    'toys': 'Find Favorite Toys',
    'varnmala': 'Varnmala',
    'vegetables': 'Name Your Veggies',
    'vehicles': 'Spot Moving Vehicles',
    'wild_animals': 'Jungle Animals',
}

CHARACTERS_100PERCENT = {
    'alladin': 'Alladin',
    'arjun': 'Arjun',
    'golu': 'Golu',
    'guddi': 'Guddi',
    'hanuman': 'Hanuman',
    'jay': 'Jay',
    'krishna': 'Krishna',
    'meera': 'Meera',
    'mia': 'Mia',
    'mishka': 'Mishka',
    'priya': 'Priya',
    'ria': 'Ria',
    'shivji': 'Shivji',
    'sindbad': 'Sindbad',
    'tara': 'Tara',
    'teja': 'Teja',
    'tenali': 'Tenali',
    'veer': 'Veer',
    'zoya': 'Zoya',
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

    def upload_to_listview(self, real_name, img_filename, img_type):
        """Upload to List View only - search by REAL category name"""
        try:
            self.driver.get(CATEGORIES_URL)
            time.sleep(4)

            # Search by REAL category name (not filename)
            search_box = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']"))
            )
            search_box.clear()
            search_box.send_keys(real_name)
            time.sleep(3)

            edit_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]"))
            )
            edit_button.click()
            time.sleep(4)

            image_path = os.path.join(PROCESSED_IMAGES_DIR, img_type, f"{img_filename}.webp")
            if not os.path.exists(image_path):
                return False

            file_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if len(file_inputs) < 1:
                return False

            abs_path = os.path.abspath(image_path)

            # Upload ONLY to first file input (List View - left side)
            try:
                file_inputs[0].send_keys(abs_path)
                time.sleep(2)
            except:
                return False

            save_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Save')]")
            save_button.click()
            time.sleep(3)
            self.upload_count += 1
            return True

        except Exception as e:
            return False

    def run(self):
        print("\n" + "="*80)
        print("UPLOADING 100% MATCHES TO LIST VIEW ONLY")
        print("="*80 + "\n")

        self.init_driver()
        if not self.login():
            print("[ERROR] Login failed")
            return

        # Upload characters
        print("CHARACTERS (19 - 100% matches):")
        for img_file, real_name in sorted(CHARACTERS_100PERCENT.items()):
            if self.upload_to_listview(real_name, img_file, "characters"):
                print(f"  ✓ {real_name}")
            else:
                print(f"  ✗ {real_name}")

        # Upload categories
        print("\nCATEGORIES (43 - 100% matches):")
        for img_file, real_name in sorted(CATEGORIES_100PERCENT.items()):
            if self.upload_to_listview(real_name, img_file, "categories"):
                print(f"  ✓ {real_name}")
            else:
                print(f"  ✗ {real_name}")

        self.close_driver()

        print("\n" + "="*80)
        print(f"COMPLETE: {self.upload_count} items uploaded")
        print("="*80 + "\n")


if __name__ == "__main__":
    uploader = CMSUploader()
    uploader.run()
