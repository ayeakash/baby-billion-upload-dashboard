"""Restore ALL trashed pages from AI Sprint database — with progress logging."""
import os, sys, io, json, time
from urllib import request, error

# Force UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Also log to a file for monitoring
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "progress.log")

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# Clear log
with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write("")

API_KEY = os.environ.get("NOTION_API_KEY")
CHILD_DS_IDS = [
    "34463e60-e8f4-8000-9691-000b77f2753b",
    "36b63e60-e8f4-8099-96e5-000b399e79ae",
]
API_VERSION = "2025-09-03"

def api_call(method, endpoint, body=None):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Notion-Version": API_VERSION,
        "Content-Type": "application/json",
    }
    url = f"https://api.notion.com/v1{endpoint}"
    data = json.dumps(body).encode("utf-8") if body else None
    
    for attempt in range(5):
        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8")), resp.status
        except error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            if e.code == 429:
                wait = min(2 ** attempt * 2, 60)
                log(f"  Rate limited! Waiting {wait}s... (attempt {attempt+1})")
                time.sleep(wait)
                continue
            try:
                return json.loads(err_body), e.code
            except:
                return {"error": err_body}, e.code
        except Exception as ex:
            wait = 5
            log(f"  Connection error: {ex}. Retrying in {wait}s...")
            time.sleep(wait)
    return {"error": "max retries"}, 429

def get_title(page):
    for pv in page.get("properties", {}).values():
        if pv.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in pv.get("title", [])) or "(Untitled)"
    return "(Untitled)"

log("=" * 50)
log("FULL RESTORE - All trashed pages in AI Sprint")
log("=" * 50)

# Step 1: Fetch ALL trashed pages
log("STEP 1: Fetching all trashed pages...")
all_trashed = []
for ds_id in CHILD_DS_IDS:
    log(f"  Querying data source: {ds_id[:12]}...")
    has_more = True
    start_cursor = None
    ds_total = 0
    while has_more:
        body = {"page_size": 100, "in_trash": True}
        if start_cursor:
            body["start_cursor"] = start_cursor
        result, status = api_call("POST", f"/data_sources/{ds_id}/query", body)
        if status != 200:
            log(f"  Error {status}")
            break
        pages = result.get("results", [])
        all_trashed.extend(pages)
        ds_total += len(pages)
        has_more = result.get("has_more", False)
        start_cursor = result.get("next_cursor")
        if ds_total % 500 == 0:
            log(f"  Fetched {ds_total}...")
    log(f"  Data source done: {ds_total} pages")

log(f"TOTAL TRASHED: {len(all_trashed)}")

# Step 2: Restore ALL
log(f"STEP 2: Restoring {len(all_trashed)} pages...")
ok = 0
fail = 0

for i, p in enumerate(all_trashed, 1):
    title = get_title(p)
    result, status = api_call("PATCH", f"/pages/{p['id']}", {"in_trash": False})
    if status == 200:
        ok += 1
    else:
        fail += 1
        log(f"  FAIL: \"{title}\" (status {status})")
    
    # Progress every 25 pages
    if i % 25 == 0:
        log(f"  Progress: {i}/{len(all_trashed)} done | OK={ok} FAIL={fail}")
    
    # Rate limit avoidance: pause 0.4s per request
    time.sleep(0.4)

log("")
log("=" * 50)
log(f"COMPLETE! Restored={ok} Failed={fail} Total={len(all_trashed)}")
log("=" * 50)
