"""
Verify which items actually have thumbnails uploaded in the CMS
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
PLAYLISTS_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/playlists"
CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"

# Items claimed to be uploaded
CLAIMED_UPLOADED = {
    'playlists': [
        'Animals', 'Around Us', 'Curious Kids', 'Geography', 'Hindi Basics',
        'Maths', 'Nature', 'Our World', 'Science', 'Stories', 'ABC Learning',
        'English Basics', 'Talk & Manners', 'Numbers & Easy Math', 'Rhymes & Music'
    ],
    'characters': [
        'Arjun', 'Golu', 'Guddi', 'Hanuman', 'Krishna', 'Mia', 'Mishka',
        'Priya', 'Shivji', 'Sindbad', 'Tara', 'Teja', 'Tenali', 'Veer', 'Zoya'
    ],
    'categories': [
        'Learn Your ABC', 'About India', 'Try These Actions', 'Aladdin',
        'Clothes', 'Learn Color names', 'What Do They Do', 'Visit New Countries',
        'Understand Your Feelings', 'Learn New Words', 'Meet Farm Animals',
        'Celebrate With Everyone', 'Choose Healthy Foods', 'Fractions',
        'Name Your Fruits', 'Practice Good Habits', 'Greater & Lesser',
        'Find Things Around', 'Knowledge', 'Mishka And Momo',
        'Shapes With Ms Isha', 'Pronounce With Ms Nidhi', 'Maths With Ms Pranika',
        'Know Body Parts', 'Meet Your Family', 'Learn Opposite Words',
        'Panchatantra', 'Let\'s Go Outside', 'Watch Plants Grow', 'Prepositions',
        'Safety', 'Read Simple Words', 'Start With Sentences', 'Visit Outer Space',
        'Explore Different Sports', 'Time', 'Find Favorite Toys', 'Varnmala',
        'Name Your Veggies', 'Spot Moving Vehicles'
    ]
}

class CMSVerifier:
    def __init__(self):
        self.driver = None
        self.wait = None

    def init_driver(self):
        print("[*] Initializing Chrome...")
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--start-maximized")
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 30)

    def close_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

    def login(self):
        print("[*] Logging in...")
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
                print("[OK] Logged in\n")
                time.sleep(2)
                return True
            except:
                time.sleep(1)
        return False

    def check_item_has_thumbnail(self, item_name, item_type):
        """Check if an item has a thumbnail by opening it and checking for images"""
        try:
            url = PLAYLISTS_URL if item_type == "playlists" else CATEGORIES_URL
            self.driver.get(url)
            time.sleep(3)

            # Search for item
            search_box = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']"))
            )
            search_box.clear()
            search_box.send_keys(item_name)
            time.sleep(2)

            # Click Edit
            try:
                edit_button = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]"))
                )
                edit_button.click()
                time.sleep(3)

                # Check for uploaded images
                images = self.driver.find_elements(By.CSS_SELECTOR, "img[src*='https']")
                has_thumbnail = len(images) > 0

                return has_thumbnail
            except:
                return False

        except Exception as e:
            return False

    def verify(self):
        print("\n" + "="*80)
        print("VERIFYING UPLOADS IN CMS")
        print("="*80 + "\n")

        self.init_driver()
        if not self.login():
            print("[ERROR] Login failed")
            return

        verified = {
            'playlists': {'yes': [], 'no': []},
            'characters': {'yes': [], 'no': []},
            'categories': {'yes': [], 'no': []}
        }

        # Verify playlists
        print("CHECKING PLAYLISTS:")
        for item in CLAIMED_UPLOADED['playlists']:
            if self.check_item_has_thumbnail(item, 'playlists'):
                print(f"  ✓ {item}")
                verified['playlists']['yes'].append(item)
            else:
                print(f"  ✗ {item}")
                verified['playlists']['no'].append(item)

        # Verify characters
        print("\nCHECKING CHARACTERS:")
        for item in CLAIMED_UPLOADED['characters']:
            if self.check_item_has_thumbnail(item, 'characters'):
                print(f"  ✓ {item}")
                verified['characters']['yes'].append(item)
            else:
                print(f"  ✗ {item}")
                verified['characters']['no'].append(item)

        # Verify categories
        print("\nCHECKING CATEGORIES:")
        for item in CLAIMED_UPLOADED['categories']:
            if self.check_item_has_thumbnail(item, 'categories'):
                print(f"  ✓ {item}")
                verified['categories']['yes'].append(item)
            else:
                print(f"  ✗ {item}")
                verified['categories']['no'].append(item)

        self.close_driver()

        print("\n" + "="*80)
        print("VERIFICATION RESULTS")
        print("="*80)
        total_yes = len(verified['playlists']['yes']) + len(verified['characters']['yes']) + len(verified['categories']['yes'])
        total_no = len(verified['playlists']['no']) + len(verified['characters']['no']) + len(verified['categories']['no'])
        print(f"\n✓ Actually Uploaded: {total_yes}")
        print(f"✗ Not Found in CMS: {total_no}")
        print(f"Total Checked: {total_yes + total_no}")
        print("="*80 + "\n")

if __name__ == "__main__":
    verifier = CMSVerifier()
    verifier.verify()
