import os, sys, time, json
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))

from config import ADMIN_BASE_URL
import uploader

def test_extract():
    driver = uploader.build_driver(headless=True)
    try:
        uploader.login(driver)
        driver.get(f"{ADMIN_BASE_URL}/dashboard/cms/video-library")
        time.sleep(3)

        sample_ids = [
            "79a23542-66e7-4813-b3ab-7b03abfe2f22",
            "b7ec7fdb-0f77-425b-9d92-df16cfdc48a0", # Hidden in screenshot
            "caa10f12-2a19-4c4a-960e-f79b3d823735"  # Hidden in screenshot
        ]

        search_inp = driver.find_element("css selector", "input.cms-filter-search")

        for vid in sample_ids:
            driver.execute_script("""
                const el = arguments[0];
                const val = arguments[1];
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                nativeInputValueSetter.call(el, val);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            """, search_inp, vid)
            time.sleep(2.0)

            rows = driver.find_elements("css selector", "table tbody tr")
            if not rows:
                print(f"[{vid}] No rows found")
                continue

            row = rows[0]
            # Extract row info via JS
            info = driver.execute_script("""
                const row = arguments[0];
                const cells = Array.from(row.querySelectorAll('td'));
                
                // Status is typically cell with .tag-pos or .tag-neg or containing Active/Hidden
                let visibilityStatus = 'Unknown';
                const statusTag = row.querySelector('.tag-pos, .tag-neg, [class*="tag"]');
                for (const cell of cells) {
                    const txt = cell.innerText.trim();
                    if (txt === 'Active' || txt === 'Hidden') {
                        visibilityStatus = txt;
                        break;
                    }
                }

                // Title
                const titleCell = row.querySelector('.vl-title-cell, td:nth-child(2)');
                const title = titleCell ? titleCell.innerText.trim() : '';

                // Language tag
                let language = 'Unknown';
                for (const cell of cells) {
                    const txt = cell.innerText.trim();
                    if (txt === 'English' || txt === 'Hindi') {
                        language = txt;
                        break;
                    }
                }

                return {
                    title: title,
                    language: language,
                    visibility_status: visibilityStatus,
                    rowText: row.innerText.trim()
                };
            """, row)

            print(f"[{vid}] Result: {json.dumps(info, indent=2)}")

    finally:
        driver.quit()

if __name__ == "__main__":
    test_extract()
