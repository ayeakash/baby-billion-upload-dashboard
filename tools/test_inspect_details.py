import os, sys, time, json
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))

from config import ADMIN_BASE_URL
import uploader

def inspect_video_details(driver, video_id: str) -> dict:
    library_url = f"{ADMIN_BASE_URL}/dashboard/cms/video-library"
    if "/dashboard/cms/video-library" not in driver.current_url:
        driver.get(library_url)
        time.sleep(2.5)

    # Close any open modal
    driver.execute_script("""
        const cancels = document.querySelectorAll('.btn-cancel, [aria-label="Close"]');
        cancels.forEach(c => c.click());
    """)
    time.sleep(0.5)

    # Search with React nativeInputValueSetter
    search_inputs = driver.find_elements("css selector", "input.cms-filter-search, input[placeholder*='Search']")
    if not search_inputs:
        driver.get(library_url)
        time.sleep(2.5)
        search_inputs = driver.find_elements("css selector", "input.cms-filter-search, input[placeholder*='Search']")
        if not search_inputs:
            return {"video_id": video_id, "status": "ERROR", "message": "Search input not found"}

    search_inp = search_inputs[0]
    driver.execute_script("""
        const el = arguments[0];
        const val = arguments[1];
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        nativeInputValueSetter.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    """, search_inp, video_id)
    time.sleep(2.0)

    # Find matching row and Edit button
    rows = driver.find_elements("css selector", "table tbody tr")
    edit_btn = None

    for row in rows:
        row_text = row.text.strip()
        if video_id.lower() in row_text.lower() or len(rows) == 1:
            btns = row.find_elements("css selector", "button")
            for btn in btns:
                if btn.text.strip().lower() == "edit":
                    edit_btn = btn
                    break
        if edit_btn:
            break

    if not edit_btn:
        return {
            "video_id": video_id,
            "status": "NOT_FOUND",
            "title": "N/A",
            "language": "N/A",
            "age_groups": [],
            "message": "Video ID not found in search results"
        }

    # Click Edit button to open modal
    driver.execute_script("arguments[0].click();", edit_btn)
    time.sleep(2.0)

    # Inspect modal with specific IDs #vl-edit-title-inp and #vl-edit-language
    modal_info = driver.execute_script("""
        const modal = document.querySelector('.bab-ref-edit-root.modal, [role="dialog"]');
        if (!modal) return null;

        // Title: specific ID #vl-edit-title-inp
        const titleInp = modal.querySelector('#vl-edit-title-inp');
        let title = titleInp ? titleInp.value.trim() : '';
        if (!title) {
            const ttlEl = modal.querySelector('.modal-ttl');
            if (ttlEl) {
                title = ttlEl.innerText.replace(/^Edit:\\s*/i, '').trim();
            }
        }

        // Language: specific ID #vl-edit-language
        const langSel = modal.querySelector('#vl-edit-language');
        let language = '';
        if (langSel && langSel.selectedIndex >= 0) {
            language = langSel.options[langSel.selectedIndex].text.trim();
        }

        // Selected Age Groups
        const chips = Array.from(modal.querySelectorAll('.chip-opt, button'));
        const selectedAgeGroups = chips
            .filter(c => ['0-3', '3-6', '6+'].includes(c.innerText.trim()) && c.className.includes('sel'))
            .map(c => c.innerText.trim());

        return {
            title: title,
            language: language,
            age_groups: selectedAgeGroups
        };
    """)

    # Close modal
    driver.execute_script("""
        const cancel = document.querySelector('.btn-cancel, [aria-label="Close"]');
        if (cancel) cancel.click();
    """)
    time.sleep(0.5)

    if not modal_info:
        return {"video_id": video_id, "status": "ERROR", "message": "Failed to inspect modal"}

    return {
        "video_id": video_id,
        "status": "SUCCESS",
        "title": modal_info["title"],
        "language": modal_info["language"],
        "age_groups": modal_info["age_groups"]
    }

def main():
    driver = uploader.build_driver(headless=True)
    try:
        uploader.login(driver)
        sample_ids = [
            "79a23542-66e7-4813-b3ab-7b03abfe2f22",
            "07fff109-52a3-4bf8-96a6-fb35f5407990"
        ]
        for vid in sample_ids:
            res = inspect_video_details(driver, vid)
            print("Inspected result:", json.dumps(res, indent=2))
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
