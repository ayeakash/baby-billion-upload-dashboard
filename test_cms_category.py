"""
test_cms_category.py — Test script to upload a 1-video test batch to CMS with Shivji category
and print the exact CMS error response / webpage text.
"""

import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(BASE_DIR, "pipeline")
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import uploader

def main():
    print("Testing CMS upload with Shivji category...")
    driver = uploader.build_driver(headless=False)
    try:
        if not uploader.login(driver):
            print("Login failed!")
            return

        driver.get(uploader.ADMIN_UPLOAD_URL)
        time.sleep(3)

        # Upload Batch_07 as a test
        print("Uploading Batch_07...")
        job_id = uploader.upload_batch(driver, "Batch_07")
        print(f"Result Job ID: {job_id}")

        time.sleep(5)
        # Capture page text
        body = driver.find_element(uploader.By.TAG_NAME, "body").text
        print("\n--- PAGE CONTENT ---")
        print(body[:1500])

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
