"""
Test Character Upload - Upload ANY character to test
Choose which character to test
"""

import os
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
CMS_CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"

# Available characters
AVAILABLE_CHARACTERS = [
    "guddi",
    "mishka",
    "krishna",
    "shivji",
    "hanuman",
    "sindbad",
    "tenali",
    "arjun",
    "veer",
    "golu",
    "jay",
    "meera",
    "mia",
    "priya",
    "ria",
    "tara",
    "teja",
    "zoya",
    "alladin",
]

# Timeouts
WAIT_TIMEOUT = 20


def list_characters():
    """List all available characters"""
    print("\nAvailable Characters:")
    print("-" * 80)
    for i, char in enumerate(AVAILABLE_CHARACTERS, 1):
        image_path = os.path.join(PROCESSED_IMAGES_DIR, "characters", f"{char}.webp")
        if os.path.exists(image_path):
            size_kb = os.path.getsize(image_path) / 1024
            print(f"{i:2}. {char:20} ({size_kb:5.1f}KB)")
    print("-" * 80)


def get_character_choice():
    """Get character choice from user"""
    list_characters()
    print("\nChoose a character to test:")
    choice = input("Enter character name (or number): ").strip().lower()

    # Check if number
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(AVAILABLE_CHARACTERS):
            return AVAILABLE_CHARACTERS[idx]
    else:
        if choice in AVAILABLE_CHARACTERS:
            return choice

    print(f"[ERROR] Invalid choice: {choice}")
    return None


def test_character_upload(character_name):
    """Test upload for a specific character"""
    character_display = character_name.capitalize()
    image_path = os.path.join(PROCESSED_IMAGES_DIR, "characters", f"{character_name}.webp")

    print("\n" + "="*80)
    print(f"TEST CHARACTER UPLOAD - {character_display.upper()}")
    print("="*80 + "\n")

    # Check image exists
    if not os.path.exists(image_path):
        print(f"[ERROR] Image not found: {image_path}")
        return False

    file_size_kb = os.path.getsize(image_path) / 1024
    print(f"[OK] Found image: {character_name}.webp ({file_size_kb:.1f}KB)")
    print(f"[*] Will upload to: {character_display}\n")

    # Initialize driver
    print("[*] Initializing Chrome WebDriver...")
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    try:
        driver = webdriver.Chrome(options=options)
        print("[OK] Chrome WebDriver initialized\n")
    except Exception as e:
        print(f"[ERROR] Failed to initialize WebDriver: {e}")
        return False

    try:
        wait = WebDriverWait(driver, WAIT_TIMEOUT)

        # Step 1: Navigate to login
        print("[Step 1/5] Navigating to login page...")
        driver.get(LOGIN_URL)
        time.sleep(2)
        print("[OK] Login page loaded\n")

        # Step 2: Login
        print("[Step 2/5] Logging in automatically...")

        # Find and fill username
        username_input = wait.until(EC.presence_of_element_located((By.ID, "username")))
        username_input.clear()
        username_input.send_keys(CMS_EMAIL)
        print(f"  [OK] Username entered: {CMS_EMAIL}")
        time.sleep(1)

        # Find and fill password
        password_input = driver.find_element(By.ID, "password")
        password_input.clear()
        password_input.send_keys(CMS_PASSWORD)
        print(f"  [OK] Password entered")
        time.sleep(1)

        # Click login button
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        print(f"  [OK] Login button clicked")
        time.sleep(3)

        # Wait for dashboard
        print("  [*] Waiting for dashboard to load...")
        wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/playlists')]")))
        print("[OK] Login successful!\n")

        # Step 3: Navigate to categories
        print("[Step 3/5] Navigating to categories...")
        driver.get(CMS_CATEGORIES_URL)
        time.sleep(3)
        print("[OK] Categories page loaded\n")

        # Step 4: Search and find character
        print(f"[Step 4/5] Searching for '{character_display}'...")
        search_box = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']")))
        search_box.clear()
        search_box.send_keys(character_display)
        time.sleep(2)
        print(f"[OK] Searched for: {character_display}\n")

        # Step 5: Click edit and upload
        print(f"[Step 5/5] Uploading image...")

        # Find edit button
        edit_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Edit')]")))
        edit_button.click()
        print(f"  [OK] Edit button clicked")
        time.sleep(3)

        # Find file input and upload
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        print(f"  [*] Found {len(file_inputs)} file input field(s)")

        if len(file_inputs) == 0:
            print(f"  [ERROR] No file input fields found!")
            return False

        abs_path = os.path.abspath(image_path)
        uploaded_count = 0

        # Upload to both fields
        for idx, file_input in enumerate(file_inputs[:2], 1):
            try:
                file_input.send_keys(abs_path)
                print(f"  [OK] Uploaded to field {idx}")
                uploaded_count += 1
                time.sleep(2)
            except Exception as e:
                print(f"  [WARN] Upload to field {idx} failed: {e}")

        if uploaded_count == 0:
            print(f"  [ERROR] Could not upload to any fields!")
            return False

        # Save
        print(f"  [*] Looking for save button...")
        save_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Save')]")
        save_button.click()
        print(f"  [OK] Save button clicked")
        time.sleep(3)

        print("\n" + "="*80)
        print(f"[SUCCESS] {character_display.upper()} UPLOAD TEST COMPLETE!")
        print("="*80 + "\n")

        print("What happened:")
        print(f"  ✓ Logged in automatically")
        print(f"  ✓ Navigated to categories")
        print(f"  ✓ Searched for '{character_display}'")
        print(f"  ✓ Clicked Edit")
        print(f"  ✓ Uploaded image from: {image_path}")
        print(f"  ✓ Uploaded to {uploaded_count} thumbnail field(s)")
        print(f"  ✓ Clicked Save")

        print("\nIf you see this message, the automation works!")
        print("Ready to run the full uploader with all images.\n")

        input("Press ENTER to close browser...")
        return True

    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        driver.quit()
        print("[OK] Browser closed")


def main():
    """Main function"""
    print("\n" + "="*80)
    print("CHARACTER UPLOAD TEST - SELECT A CHARACTER")
    print("="*80)

    # Get character choice
    character = get_character_choice()
    if not character:
        return

    # Run test
    success = test_character_upload(character)

    if success:
        print("\n" + "="*80)
        print("NEXT: Run full uploader with:")
        print("  python cms_auto_uploader_fixed.py")
        print("="*80)
    else:
        print("\n[ERROR] Test failed. Fix issues above before running full uploader.")


if __name__ == "__main__":
    main()
