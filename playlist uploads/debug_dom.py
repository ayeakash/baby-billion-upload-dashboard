"""Debug: dump actual categories page HTML to understand real DOM structure."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
from config import BB_USERNAME, BB_PASSWORD  # from credentials.py / env — never hardcode

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

try:
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.chrome.service import Service
    service = Service(ChromeDriverManager().install())
except ImportError:
    service = None

BASE_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com"

opts = Options()
opts.add_argument("--start-maximized")
if service:
    driver = webdriver.Chrome(service=service, options=opts)
else:
    driver = webdriver.Chrome(options=opts)

# Login
driver.get(f"{BASE_URL}/login")
time.sleep(3)
driver.find_element(By.CSS_SELECTOR, "input[type='text'], input[type='email']").send_keys(BB_USERNAME)
driver.find_element(By.CSS_SELECTOR, "input[type='password']").send_keys(BB_PASSWORD)
driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
time.sleep(5)
print(f"After login URL: {driver.current_url}")

# Navigate explicitly to categories
driver.get(f"{BASE_URL}/dashboard/cms/categories")
time.sleep(5)
print(f"Categories URL: {driver.current_url}")

# Dump a chunk of the page source to see actual HTML structure
page_src = driver.page_source
# Find "Edit" buttons to locate category cards
edit_idx = page_src.find("Edit")
if edit_idx > 0:
    # Show surrounding HTML
    start = max(0, edit_idx - 1000)
    end = min(len(page_src), edit_idx + 500)
    snippet = page_src[start:end]
    print(f"\n=== HTML around first 'Edit' button (chars {start}-{end}) ===")
    print(snippet)
else:
    print("No 'Edit' text found in page source!")

# Also try JS to find all unique class names on the page
classes_js = """
return (() => {
    const allClasses = new Set();
    document.querySelectorAll('*').forEach(el => {
        if (el.className && typeof el.className === 'string') {
            el.className.split(/\\s+/).forEach(c => {
                if (c.length > 2) allClasses.add(c);
            });
        }
    });
    return Array.from(allClasses).sort().join(', ');
})();
"""
classes = driver.execute_script(classes_js)
print(f"\n=== ALL CSS CLASSES on page ===")
print(classes)

# Try to find any element containing 'Safety' text
safety_js = """
return (() => {
    const results = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while (node = walker.nextNode()) {
        if (node.textContent.trim() === 'Safety') {
            const el = node.parentElement;
            results.push({
                tag: el.tagName,
                class: el.className,
                parentTag: el.parentElement ? el.parentElement.tagName : 'none',
                parentClass: el.parentElement ? el.parentElement.className : 'none',
                grandparentTag: el.parentElement && el.parentElement.parentElement ? el.parentElement.parentElement.tagName : 'none',
                grandparentClass: el.parentElement && el.parentElement.parentElement ? el.parentElement.parentElement.className : 'none',
            });
        }
    }
    return JSON.stringify(results, null, 2);
})();
"""
safety = driver.execute_script(safety_js)
print(f"\n=== Elements containing exact 'Safety' text ===")
print(safety)

# Count common selectors
count_js = """
return JSON.stringify({
    'div': document.querySelectorAll('div').length,
    'button': document.querySelectorAll('button').length,
    'span': document.querySelectorAll('span').length,
    '.cms-list-item': document.querySelectorAll('.cms-list-item').length,
    '[class*=cat]': document.querySelectorAll('[class*=cat]').length,
    '[class*=item]': document.querySelectorAll('[class*=item]').length,
    '[class*=list]': document.querySelectorAll('[class*=list]').length,
    '[class*=card]': document.querySelectorAll('[class*=card]').length,
    '[class*=edit]': document.querySelectorAll('[class*=edit]').length,
    '[class*=category]': document.querySelectorAll('[class*=category]').length,
});
"""
counts = driver.execute_script(count_js)
print(f"\n=== Selector counts ===")
print(counts)

input("\nPress Enter to close...")
driver.quit()
