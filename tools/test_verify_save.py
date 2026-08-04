import os, sys, time
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))

from config import ADMIN_BASE_URL
import uploader

def verify():
    driver = uploader.build_driver(headless=True)
    try:
        uploader.login(driver)
        driver.get(f"{ADMIN_BASE_URL}/dashboard/cms/video-library")
        time.sleep(3)
        
        vid = "18990203-35bd-4570-94e4-6112cc83c565"
        
        # Search
        inp = driver.find_element("css selector", "input.cms-filter-search")
        driver.execute_script("""
            const el = arguments[0];
            el.value = arguments[1];
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """, inp, vid)
        time.sleep(2)
        
        # Click Edit
        btns = driver.find_elements("css selector", "button")
        for b in btns:
            if b.text.strip() == "Edit":
                driver.execute_script("arguments[0].click();", b)
                break
        time.sleep(2)
        
        # Check chips status
        modal = driver.find_element("css selector", ".bab-ref-edit-root.modal")
        chips = modal.find_elements("css selector", ".chip-opt")
        selected_chips = [c.text.strip() for c in chips if "sel" in c.get_attribute("class")]
        print("Verified selected age group chips in CMS modal:", selected_chips)
    finally:
        driver.quit()

if __name__ == "__main__":
    verify()
