"""Quick script to check CMS video library IDs vs Characters.csv IDs"""
import sys, os, time, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline'))
import config as cfg, uploader

driver = uploader.build_driver(headless=False)
try:
    if not uploader.login(driver):
        print("Login failed!"); sys.exit(1)

    # Go to video library
    driver.get(f"{cfg.ADMIN_BASE_URL}/dashboard/cms/video-library")
    time.sleep(5)

    # Get page content - dump structure
    result = driver.execute_script("""
    return (() => {
        const data = {};
        // Get page title
        data.title = document.title;
        data.url = window.location.href;
        
        // Get all table content
        const tables = document.querySelectorAll('table');
        data.tables = tables.length;
        
        if (tables.length > 0) {
            const headers = [];
            tables[0].querySelectorAll('th').forEach(th => headers.push(th.innerText.trim()));
            data.headers = headers;
            
            const rows = [];
            tables[0].querySelectorAll('tbody tr').forEach((tr, i) => {
                if (i < 10) {
                    const cells = [];
                    tr.querySelectorAll('td').forEach(td => cells.push(td.innerText.trim().substring(0, 100)));
                    rows.push(cells);
                }
            });
            data.rows = rows;
        }
        
        // Get all text that looks like UUIDs
        const body = document.body.innerText;
        const uuids = body.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi) || [];
        data.uuids_found = uuids.slice(0, 20);
        
        // Get first 3000 chars of body text
        data.body_preview = body.substring(0, 3000);
        
        return data;
    })();
    """)
    
    print(json.dumps(result, indent=2))

finally:
    input("\nPress Enter to close...")
    driver.quit()
