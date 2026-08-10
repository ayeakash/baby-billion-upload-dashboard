"""
Diagnose Login Form - Shows what's actually on the login page
"""

import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

LOGIN_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com"

print("\n" + "="*80)
print("LOGIN FORM DIAGNOSTICS")
print("="*80 + "\n")

print("[*] Opening browser...")
options = Options()
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(options=options)

print("[*] Navigating to login page...")
driver.get(LOGIN_URL)
time.sleep(5)

print("[*] Analyzing login form...\n")

# Get page source
page_source = driver.page_source

# Find all input elements
print("INPUT FIELDS FOUND:")
print("-" * 80)

# Look for input elements
import re
inputs = re.findall(r'<input[^>]*>', page_source)
for i, inp in enumerate(inputs[:10], 1):
    print(f"{i}. {inp}\n")

# Look for form elements
print("\nFORM ELEMENTS FOUND:")
print("-" * 80)
forms = re.findall(r'<form[^>]*>', page_source)
for form in forms:
    print(f"- {form}\n")

# Look for buttons
print("\nBUTTON ELEMENTS FOUND:")
print("-" * 80)
buttons = re.findall(r'<button[^>]*>[^<]*</button>', page_source)
for i, btn in enumerate(buttons[:10], 1):
    print(f"{i}. {btn}")

print("\n" + "="*80)
print("SCREENSHOT SAVED")
print("="*80)

# Take screenshot
driver.save_screenshot("login_page_screenshot.png")
print("\n[OK] Screenshot saved: login_page_screenshot.png")
print("[*] Browser stays open - check the login form visually")
print("[*] Look for email/password input fields")
print("[*] Right-click on elements to inspect them\n")

input("Press ENTER to close...")
driver.quit()
