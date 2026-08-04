import os, sys, time, json
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))

from config import ADMIN_BASE_URL
import uploader

def inspect_79a():
    driver = uploader.build_driver(headless=True)
    try:
        uploader.login(driver)
        driver.get(f"{ADMIN_BASE_URL}/dashboard/cms/video-library")
        time.sleep(3)

        vid = "79a23542-66e7-4813-b3ab-7b03abfe2f22"

        # Search
        inp = driver.find_element("css selector", "input.cms-filter-search")
        driver.execute_script("""
            const el = arguments[0];
            el.value = arguments[1];
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """, inp, vid)
        time.sleep(2)

        # Print table row html/text before edit
        row = driver.find_element("css selector", "table tbody tr")
        print("Table Row Text:", repr(row.text))
        print("Table Row HTML:", row.get_attribute("outerHTML"))

        # Click Edit
        btns = row.find_elements("css selector", "button")
        for b in btns:
            if b.text.strip().lower() == "edit":
                driver.execute_script("arguments[0].click();", b)
                break
        time.sleep(2)

        # Inspect Modal Age Group section
        modal = driver.find_element("css selector", ".bab-ref-edit-root.modal")
        print("\n=== MODAL AGE GROUPS DOM ===")
        age_section_info = driver.execute_script("""
            const modal = document.querySelector('.bab-ref-edit-root.modal');
            const chips = Array.from(modal.querySelectorAll('.chip-opt, button')).filter(b => ['0-3', '3-6', '6+'].includes(b.innerText.trim()));
            return chips.map(c => ({
                text: c.innerText.trim(),
                className: c.className,
                outerHTML: c.outerHTML
            }));
        """)
        print(json.dumps(age_section_info, indent=2))

    finally:
        driver.quit()

if __name__ == "__main__":
    inspect_79a()
