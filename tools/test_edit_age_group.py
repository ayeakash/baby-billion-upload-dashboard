import os, sys, time
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))

from config import ADMIN_BASE_URL
import uploader

def update_age_group_for_video(driver, video_id: str, target_age_groups: list[str]) -> bool:
    """
    Navigates to Video Library, searches for video_id, clicks Edit,
    sets target_age_groups (e.g. ['0-3', '3-6']), and clicks 'Save Changes'.
    """
    library_url = f"{ADMIN_BASE_URL}/dashboard/cms/video-library"
    if "/dashboard/cms/video-library" not in driver.current_url:
        driver.get(library_url)
        time.sleep(3)
        
    # Find search input
    search_inp = None
    inputs = driver.find_elements("css selector", "input.cms-filter-search, input[placeholder*='Search']")
    if inputs:
        search_inp = inputs[0]
    
    if not search_inp:
        print(f"[-] Search input not found for video {video_id}")
        return False

    # Clear and type video_id into search tab/input
    search_inp.clear()
    # Using JS clear & value assignment to trigger React state if necessary
    driver.execute_script("""
        const el = arguments[0];
        const val = arguments[1];
        el.value = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    """, search_inp, video_id)
    time.sleep(2)

    # Find the edit button in the search results
    rows = driver.find_elements("css selector", "table tbody tr, .cms-video-card, .cms-list-item")
    print(f"[*] Found {len(rows)} matching rows for video_id '{video_id}'")

    edit_btn = None
    # Look for edit button
    for row in rows:
        text = row.text
        if video_id.lower() in text.lower() or len(rows) == 1:
            btns = row.find_elements("css selector", "button")
            for b in btns:
                if b.text.strip().lower() == "edit":
                    edit_btn = b
                    break
        if edit_btn:
            break

    if not edit_btn:
        # Fallback: look for any Edit button on page
        all_btns = driver.find_elements("css selector", "button")
        for b in all_btns:
            if b.text.strip().lower() == "edit":
                edit_btn = b
                break

    if not edit_btn:
        print(f"[-] Edit button not found for video {video_id}")
        return False

    driver.execute_script("arguments[0].click();", edit_btn)
    time.sleep(2)

    # Locate age group chips in modal
    # In modal: find chip buttons under Age Groups section
    modal = driver.find_element("css selector", ".bab-ref-edit-root.modal, [role='dialog'], .cu-modal-overlay")
    
    # Standardize target age group strings
    normalized_targets = set()
    for ag in target_age_groups:
        ag_clean = ag.strip()
        if ag_clean in ["0-3", "3-6", "6+"]:
            normalized_targets.add(ag_clean)
        elif "3" in ag_clean and "6" not in ag_clean and "0" in ag_clean:
            normalized_targets.add("0-3")
        elif "3" in ag_clean and "6" in ag_clean:
            normalized_targets.add("3-6")
        elif "6" in ag_clean:
            normalized_targets.add("6+")

    print(f"[*] Target age groups normalized: {normalized_targets}")

    # Find all chip options
    chips = modal.find_elements("css selector", ".chip-opt, button")
    age_chips = [c for c in chips if c.text.strip() in ["0-3", "3-6", "6+"]]

    for chip in age_chips:
        chip_label = chip.text.strip()
        is_selected = "sel" in chip.get_attribute("class")
        should_be_selected = chip_label in normalized_targets
        
        if is_selected != should_be_selected:
            print(f"[*] Toggling age group '{chip_label}' (currently {is_selected} -> target {should_be_selected})")
            driver.execute_script("arguments[0].click();", chip)
            time.sleep(0.5)

    # Click Save Changes
    save_btn = None
    for b in modal.find_elements("css selector", "button"):
        if "save changes" in b.text.strip().lower() or "save" in b.text.strip().lower():
            save_btn = b
            break

    if not save_btn:
        print(f"[-] Save button not found in edit modal")
        return False

    driver.execute_script("arguments[0].click();", save_btn)
    print(f"[+] Clicked 'Save Changes' for video {video_id}")
    time.sleep(3)
    return True

if __name__ == "__main__":
    print("Testing edit age group logic...")
    driver = uploader.build_driver(headless=True)
    try:
        if uploader.login(driver):
            # Test with a dummy or first video ID
            driver.get(f"{ADMIN_BASE_URL}/dashboard/cms/video-library")
            time.sleep(3)
            # Find first video ID text from page
            vid = driver.execute_script("""
                const row = document.querySelector('table tbody tr');
                if (row) {
                    const text = row.innerText;
                    const m = text.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
                    if (m) return m[0];
                }
                return null;
            """)
            print("Found sample video ID:", vid)
            if vid:
                # Get current selected chips first to keep state
                res = update_age_group_for_video(driver, vid, ["0-3", "3-6"])
                print("Update test result:", res)
    finally:
        driver.quit()
