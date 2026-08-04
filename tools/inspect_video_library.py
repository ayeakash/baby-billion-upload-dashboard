import os, sys, time, json
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))

from config import ADMIN_BASE_URL
import uploader

def main():
    print("Launching browser for edit modal inspection...")
    driver = uploader.build_driver(headless=True)
    try:
        if not uploader.login(driver):
            print("Login failed!")
            return
        
        target_url = f"{ADMIN_BASE_URL}/dashboard/cms/video-library"
        driver.get(target_url)
        time.sleep(4)
        
        # Click the first 'Edit' button
        edit_buttons = driver.find_elements("css selector", "button")
        target_btn = None
        for btn in edit_buttons:
            if btn.text.strip() == "Edit":
                target_btn = btn
                break
        
        if not target_btn:
            print("No Edit button found!")
            return
            
        print("Clicking Edit button...")
        driver.execute_script("arguments[0].click();", target_btn)
        time.sleep(3)
        
        modal_info = driver.execute_script("""
        return (() => {
            const modal = document.querySelector('.modal, [class*="modal"], [class*="overlay"], [role="dialog"], form') || document.body;
            
            const inputs = Array.from(modal.querySelectorAll('input, select, textarea')).map(i => ({
                tag: i.tagName,
                type: i.type,
                name: i.name,
                id: i.id,
                placeholder: i.placeholder,
                className: i.className,
                value: i.value,
                checked: i.checked,
                options: i.tagName === 'SELECT' ? Array.from(i.options).map(o => ({text: o.text, value: o.value, selected: o.selected})) : null
            }));
            
            const labels = Array.from(modal.querySelectorAll('label, div, span, h1, h2, h3, h4')).map(l => l.innerText?.trim()).filter(t => t && t.length < 100);
            
            const buttons = Array.from(modal.querySelectorAll('button, input[type="submit"]')).map(b => ({
                text: b.innerText?.trim() || b.value,
                className: b.className,
                type: b.type
            }));
            
            return {
                modalHTMLSnippet: modal.outerHTML.substring(0, 3000),
                inputs: inputs,
                buttons: buttons,
                labelsSnippet: labels.slice(0, 40)
            };
        })();
        """)
        
        print("\n=== MODAL INSPECTION ===")
        print(json.dumps(modal_info, indent=2))
        
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
