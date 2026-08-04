import os, sys, time, json
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))

from config import ADMIN_BASE_URL
import uploader

def update_and_verify_79a():
    driver = uploader.build_driver(headless=True)
    try:
        uploader.login(driver)
        driver.get(f"{ADMIN_BASE_URL}/dashboard/cms/video-library")
        time.sleep(3)

        target_vid = "79a23542-66e7-4813-b3ab-7b03abfe2f22"

        # Search with React nativeInputValueSetter
        search_inp = driver.find_element("css selector", "input.cms-filter-search")
        driver.execute_script("""
            const el = arguments[0];
            const val = arguments[1];
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            nativeInputValueSetter.call(el, val);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """, search_inp, target_vid)
        time.sleep(2)

        row = driver.find_element("css selector", "table tbody tr")
        print("Search row found:", row.text)

        # Click Edit
        edit_btn = row.find_element("css selector", "button")
        driver.execute_script("arguments[0].click();", edit_btn)
        time.sleep(2)

        modal = driver.find_element("css selector", ".bab-ref-edit-root.modal")
        modal_title = modal.find_element("css selector", ".modal-ttl, h2, h3").text
        print("Modal Title:", modal_title)

        # Select all 3 age groups
        chips = modal.find_elements("css selector", ".chip-opt, button")
        age_chips = [c for c in chips if c.text.strip() in ["0-3", "3-6", "6+"]]

        for chip in age_chips:
            is_sel = "sel" in chip.get_attribute("class")
            print(f"Chip '{chip.text.strip()}' initially selected: {is_sel}")
            if not is_sel:
                print(f"Clicking chip '{chip.text.strip()}' to select...")
                driver.execute_script("arguments[0].click();", chip)
                time.sleep(0.3)

        # Save Changes
        save_btn = None
        for b in modal.find_elements("css selector", "button"):
            if "save changes" in b.text.strip().lower():
                save_btn = b
                break

        print("Clicking Save Changes...")
        driver.execute_script("arguments[0].click();", save_btn)
        time.sleep(3)

        # Now re-open modal to verify saved state!
        print("\n--- RE-OPENING MODAL TO VERIFY ---")
        driver.get(f"{ADMIN_BASE_URL}/dashboard/cms/video-library")
        time.sleep(3)
        search_inp = driver.find_element("css selector", "input.cms-filter-search")
        driver.execute_script("""
            const el = arguments[0];
            const val = arguments[1];
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            nativeInputValueSetter.call(el, val);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """, search_inp, target_vid)
        time.sleep(2)

        row = driver.find_element("css selector", "table tbody tr")
        edit_btn = row.find_element("css selector", "button")
        driver.execute_script("arguments[0].click();", edit_btn)
        time.sleep(2)

        modal = driver.find_element("css selector", ".bab-ref-edit-root.modal")
        chips = modal.find_elements("css selector", ".chip-opt, button")
        verified_selected = [c.text.strip() for c in chips if c.text.strip() in ["0-3", "3-6", "6+"] and "sel" in c.get_attribute("class")]
        print("VERIFIED SELECTED AGE GROUPS IN CMS:", verified_selected)

    finally:
        driver.quit()

if __name__ == "__main__":
    update_and_verify_79a()
