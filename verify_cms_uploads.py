"""
verify_and_fix.py — Scrape CMS, save raw data, do smart matching.
"""
from __future__ import annotations
import csv, json, os, re, sys, time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))
import config as cfg, uploader

BATCHES_FILE = os.path.join(BASE_DIR, "batches.json")
BATCHES_DIR = os.path.join(BASE_DIR, "batches")
UPLOAD_HISTORY_URL = f"{cfg.ADMIN_BASE_URL}/dashboard/cms/video-upload"
SCRAPED_DATA_FILE = os.path.join(BASE_DIR, "cms_scraped.json")

def normalize(name):
    return re.sub(r'_+', '_', re.sub(r'[^\w]', '_', name.lower().strip())).strip('_')

def get_batch_video_names(bn):
    csv_path = os.path.join(BATCHES_DIR, f"{bn}.csv")
    if not os.path.exists(csv_path): return set()
    names = set()
    with open(csv_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vn = row.get("video_name", "").strip()
            if vn: names.add(normalize(vn))
    return names

def go_to_history(driver, By):
    driver.get(UPLOAD_HISTORY_URL)
    time.sleep(3)
    for el in driver.find_elements(By.CSS_SELECTOR, "button, a, span"):
        if "upload history" in el.text.strip().lower():
            try: el.click()
            except: pass
            break
    time.sleep(2)

def main():
    _, _, _, By, *_ = uploader._get_selenium()
    local = json.load(open(BATCHES_FILE))

    # Build local video name sets
    local_sets = {}
    for bn in sorted(local.keys()):
        names = get_batch_video_names(bn)
        if names: local_sets[bn] = names

    print("  Launching browser...")
    driver = uploader.build_driver(headless=False)

    try:
        if not uploader.login(driver):
            print("  Login failed!"); return

        go_to_history(driver, By)
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        
        # Get all batch IDs first
        entries = []
        for row in rows:
            cells = row.find_elements(By.CSS_SELECTOR, "td")
            if len(cells) >= 7:
                bid = cells[0].text.strip()
                if re.match(r'[0-9a-f]{8}-', bid, re.I):
                    entries.append({
                        "batch_id": bid,
                        "total": int(cells[3].text.strip()) if cells[3].text.strip().isdigit() else 0,
                        "success": int(cells[4].text.strip()) if cells[4].text.strip().isdigit() else 0,
                        "status": cells[6].text.strip(),
                    })
        
        print(f"  Found {len(entries)} CMS entries\n")
        
        # Scrape video names from each
        for i, e in enumerate(entries):
            bid = e["batch_id"]
            print(f"  [{i+1}/{len(entries)}] {bid[:25]}... ({e['total']} videos)", end="", flush=True)
            
            go_to_history(driver, By)
            
            # Click View
            clicked = False
            for row in driver.find_elements(By.CSS_SELECTOR, "table tbody tr"):
                cells = row.find_elements(By.CSS_SELECTOR, "td")
                if len(cells) >= 1 and bid in cells[0].text:
                    for btn in cells[-1].find_elements(By.CSS_SELECTOR, "button, a"):
                        if "view" in btn.text.strip().lower():
                            driver.execute_script("arguments[0].click();", btn)
                            time.sleep(3)
                            clicked = True
                            break
                    break
            
            if not clicked:
                print(" ⚠️ skip")
                e["videos"] = []
                continue
            
            # Get ALL text from page, extract video-name-like strings
            body = driver.execute_script("return document.body.innerText || ''")
            
            # Look for TITLE column values specifically
            video_names = []
            lines = body.split("\n")
            for j, line in enumerate(lines):
                line = line.strip()
                if not line: continue
                # Video titles have underscores and are like "Kids_Something_Something"
                if re.match(r'^[A-Z][a-z]+_[A-Z]', line) or re.match(r'^Kids_', line, re.I):
                    video_names.append(line)
                # Also catch names in table rows - look for lines between UUIDs
                elif "_" in line and len(line) > 5 and len(line) < 100:
                    # Skip known non-video strings
                    llow = line.lower()
                    if any(x in llow for x in ["batch", "upload", "cms", "http", "babybillion", 
                                                "video_id", "content", "log out", "ms bubble",
                                                "video upload", "processed", "submit", "reject"]):
                        continue
                    video_names.append(line)
            
            e["videos"] = video_names
            print(f" → {len(video_names)} videos")
        
        # Save raw scraped data
        json.dump(entries, open(SCRAPED_DATA_FILE, "w"), indent=2)
        print(f"\n  Saved raw data to {SCRAPED_DATA_FILE}\n")
        
    finally:
        driver.quit()
    
    # Now do matching
    print("  ═══ MATCHING ═══")
    
    used_bids = set()
    used_bns = set()
    matches = {}
    
    # Pass 1: exact video name matches
    for e in entries:
        if not e["videos"]: continue
        cms_names = {normalize(v) for v in e["videos"]}
        
        best_bn, best_score = None, 0
        for bn, local_names in local_sets.items():
            if bn in used_bns: continue
            overlap = len(cms_names & local_names)
            if overlap > best_score:
                best_score = overlap
                best_bn = bn
        
        if best_bn and best_score >= 2:  # At least 2 matching video names
            total = max(len(cms_names), len(local_sets[best_bn]))
            pct = best_score / total * 100
            if pct >= 50:
                matches[e["batch_id"]] = best_bn
                used_bids.add(e["batch_id"])
                used_bns.add(best_bn)
                icon = "✅" if pct >= 70 else "⚠️"
                print(f"  {icon} {e['batch_id'][:25]}... → {best_bn} ({best_score}/{total}, {pct:.0f}%)")
    
    # Show unmatched
    print(f"\n  Matched: {len(matches)}")
    
    unmatched_cms = [e for e in entries if e["batch_id"] not in used_bids and e["videos"]]
    unmatched_local = [bn for bn in local_sets if bn not in used_bns and bn.startswith("Batch_")]
    
    if unmatched_cms:
        print(f"\n  Unmatched CMS entries:")
        for e in unmatched_cms:
            vids = ", ".join(e["videos"][:3])
            print(f"    {e['batch_id'][:25]}... ({e['total']} vids): {vids}...")
    
    if unmatched_local:
        print(f"\n  Unmatched local batches:")
        for bn in sorted(unmatched_local):
            names = list(local_sets[bn])[:3]
            print(f"    {bn} ({len(local_sets[bn])} vids): {', '.join(names)}...")
    
    # Apply
    print(f"\n  ═══ APPLYING FIXES ═══")
    
    for bid, bn in matches.items():
        b = local[bn]
        old = b.get("upload_job_id")
        if old != bid:
            print(f"  [FIX] {bn}: job → {bid[:25]}...")
        b["upload_job_id"] = bid
        b["upload_failed"] = False
        b["fail_reason"] = None
        b["upload_completed"] = True
        b["status"] = "pending_second_review"
        for v in b.get("videos", []): v["pipeline_status"] = "uploaded_pending_final_review"
    
    # Unmatched local batches stay pending
    for bn in unmatched_local:
        b = local[bn]
        if b.get("status") != "pending_first_review":
            b["upload_job_id"] = None
            b["upload_failed"] = False
            b["upload_completed"] = False
            b["status"] = "pending_first_review"
            for v in b.get("videos", []): v["pipeline_status"] = "batched"
            print(f"  [RESET] {bn} → pending (no CMS match)")
    
    json.dump(local, open(BATCHES_FILE, "w"), indent=2)
    
    # Final summary
    print(f"\n  ═══ FINAL STATE ═══")
    uploaded = [bn for bn in sorted(local.keys()) if local[bn].get("status") == "pending_second_review"]
    pending = [bn for bn in sorted(local.keys()) if local[bn].get("status") == "pending_first_review"]
    print(f"  Uploaded ({len(uploaded)}): {', '.join(uploaded)}")
    print(f"  Pending  ({len(pending)}): {', '.join(pending)}")
    print(f"  Done!")

if __name__ == "__main__":
    main()
