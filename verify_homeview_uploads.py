"""
Verify how many categories have Home View thumbnails uploaded
"""

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

WAIT_TIMEOUT = 30

CATEGORIES = [
    'Learn Your ABC',
    'About India',
    'Try These Actions',
    'Aladdin',
    'Clothes',
    'Learn Color names',
    'What Do They Do',
    'Visit New Countries',
    'Understand Your Feelings',
    'Learn New Words',
    'Meet Farm Animals',
    'Celebrate With Everyone',
    'Choose Healthy Foods',
    'Fractions',
    'Name Your Fruits',
    'Practice Good Habits',
    'Greater & Lesser',
    'Hanuman',
    'Find Things Around',
    'Knowledge',
    'Krishna',
    'Mishka And Momo',
    'Shapes With Ms Isha',
    'Pronounce With Ms Nidhi',
    'Maths With Ms Pranika',
    'Know Body Parts',
    'Meet Your Family',
    'Learn Opposite Words',
    'Panchatantra',
    'Let\'s Go Outside',
    'Watch Plants Grow',
    'Prepositions',
    'Safety',
    'Shivji',
    'Read Simple Words',
    'Start With Sentences',
    'Sindbad',
    'Visit Outer Space',
    'Explore Different Sports',
    'Tenali',
    'Time',
    'Find Favorite Toys',
    'Varnmala',
    'Name Your Veggies',
    'Spot Moving Vehicles',
    'Jungle Animals',
]

class VerifyUploader:
    def __init__(self):
        self.driver = None
        self.wait = None

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

    def check_homeview(self, category_name):
        """Check if category has Home View thumbnail"""
        try:
            self.driver.get(CATEGORIES_URL)
            time.sleep(3)

            search_box = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']"))
            )
            search_box.clear()
            search_box.send_keys(category_name)
            time.sleep(2)

            edit_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]"))
            )
            edit_button.click()
            time.sleep(3)

            # Check if Home view has an image
            # Look for img tags that indicate an uploaded image
            home_images = self.driver.find_elements(By.XPATH, "//div[contains(text(), 'Home view')]/following::img")

            if len(home_images) > 0:
                return True

            # Alternative check - look for image in the Home view section
            try:
                home_section = self.driver.find_element(By.XPATH, "//*[contains(text(), 'Home view')]")
                parent = home_section.find_element(By.XPATH, "ancestor::div[contains(@class, 'col') or contains(@class, 'div')]")
                img = parent.find_element(By.TAG_NAME, "img")
                return True
            except:
                return False

        except Exception as e:
            return False

    def run(self):
        print("\n" + "="*80)
        print("VERIFYING HOME VIEW UPLOADS FOR CATEGORIES")
        print("="*80 + "\n")

        self.init_driver()
        if not self.login():
            print("[ERROR] Login failed")
            return

        uploaded = []
        not_uploaded = []

        print("CHECKING CATEGORIES:")
        for i, category in enumerate(sorted(CATEGORIES), 1):
            if self.check_homeview(category):
                uploaded.append(category)
                print(f"  [{i:2d}] [UPLOADED] {category}")
            else:
                not_uploaded.append(category)
                print(f"  [{i:2d}] [EMPTY] {category}")

        self.close_driver()

        print("\n" + "="*80)
        print(f"SUMMARY: {len(uploaded)} categories uploaded to HOME VIEW")
        print(f"Not uploaded: {len(not_uploaded)} categories")
        print("="*80 + "\n")

        if not_uploaded:
            print("CATEGORIES WITHOUT HOME VIEW:")
            for cat in not_uploaded:
                print(f"  - {cat}")
            print()


if __name__ == "__main__":
    verifier = VerifyUploader()
    verifier.run()
