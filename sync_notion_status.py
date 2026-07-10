"""
Mark uploaded videos on Notion using page IDs from upload_history.jsonl.
Sets Upload Progress = 'first review', Upload = Yes, Upload Date = today.
"""
import json, re, os, sys, io, time

# Fix encoding for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))
import notion_client

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upload_history.jsonl")

# CMS batch IDs that are COMPLETED
cms_completed = {
    "b655a33e-ef6b-456e-9997-be36355b672a",
    "21793618-5036-4ce2-a3cb-1e858881d785",
    "92609673-1792-49c0-b3eb-c1780c5f39ef",
    "f7eb5ff9-d6fc-474f-a001-f811d42b2479",
    "30f86cd9-e4ea-433e-9548-48eaec163109",
    "9df9eaa5-b47c-4ded-b2dd-bc42749ed5e0",
    "1a05f317-db21-4aac-aaac-2524a4e39ca5",
}

# Read all history entries
history = []
with open(HISTORY_FILE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            history.append(json.loads(line))

# Extract page IDs from video names
page_id_pattern = re.compile(r"___pg_([a-f0-9]+)")
lang_pattern = re.compile(r"(___ln_(?:Hi|En))$")

# Track unique page_ids for COMPLETED uploads only
pages_to_mark = {}  # page_id -> {"video_name": ..., "lang_suffix": ...}

for entry in history:
    vn = entry.get("video_name", "")
    job_id = entry.get("job_id", "")
    
    # Only process entries whose CMS batch actually COMPLETED
    if job_id not in cms_completed:
        continue
    
    # Extract page_id
    m = page_id_pattern.search(vn)
    if not m:
        continue
    
    raw_pid = m.group(1)
    if len(raw_pid) == 32:
        pid = f"{raw_pid[:8]}-{raw_pid[8:12]}-{raw_pid[12:16]}-{raw_pid[16:20]}-{raw_pid[20:]}"
    else:
        pid = raw_pid
    
    # Extract language suffix
    lang_match = lang_pattern.search(vn)
    lang_suffix = lang_match.group(1) if lang_match else None
    
    # Extract clean video name (strip ___pg_... and ___ln_... suffixes)
    clean_name = re.sub(r"___pg_[a-f0-9]+", "", vn)
    clean_name = re.sub(r"___ln_(?:Hi|En)$", "", clean_name)
    
    pages_to_mark[pid] = {
        "video_name": clean_name,
        "lang_suffix": lang_suffix,
        "job_id": job_id,
        "batch": entry.get("batch_name", ""),
    }

print(f"Found {len(pages_to_mark)} videos from COMPLETED CMS batches to mark on Notion\n")

success_count = 0
error_count = 0

for pid, data in sorted(pages_to_mark.items(), key=lambda x: x[1]["batch"]):
    try:
        ok = notion_client.mark_uploaded_in_notion(
            page_id=pid,
            video_name=data["video_name"],
            lang_suffix=data["lang_suffix"],
        )
        if ok:
            success_count += 1
            print(f"  [OK] {data['batch']} | {pid[:20]}... | {data['video_name'][:40]}")
        else:
            error_count += 1
            print(f"  [FAIL] {data['batch']} | {pid[:20]}... | mark returned False")
        
        time.sleep(0.35)  # Notion rate limit
    except Exception as e:
        error_count += 1
        print(f"  [ERROR] {data['batch']} | {pid[:20]}... | {e}")

print(f"\nDone! {success_count} marked as uploaded on Notion, {error_count} errors")
