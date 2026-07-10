"""Final pre-upload check: verify all pending batches are ready."""
import json, os, csv, zipfile, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BATCHES_DIR = "batches"
b = json.load(open("batches.json", "r", encoding="utf-8"))

ready = 0
fixed = 0
problems = 0

for bn, d in sorted(b.items()):
    if d.get("status") != "pending_first_review":
        continue
    
    # Clear any failed flags
    if d.get("upload_failed"):
        d["upload_failed"] = False
        d["upload_job_id"] = ""
        d.pop("fail_reason", None)
        fixed += 1
    
    csv_path = os.path.join(BATCHES_DIR, f"{bn}.csv")
    zip_path = os.path.join(BATCHES_DIR, f"{bn}.zip")
    
    # Check CSV
    if not os.path.isfile(csv_path):
        print(f"  PROBLEM {bn}: NO CSV")
        problems += 1
        continue
    
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    
    csv_names = [r.get("video_name", "") for r in rows]
    
    # Check ZIP
    if not os.path.isfile(zip_path):
        # Try to create ZIP from batch folder
        batch_dir = os.path.join(BATCHES_DIR, bn)
        if os.path.isdir(batch_dir):
            print(f"  CREATING ZIP for {bn}...")
            import zipfile as zf
            with zf.ZipFile(zip_path, "w", zf.ZIP_DEFLATED) as z:
                for fname in os.listdir(batch_dir):
                    if fname.endswith((".mp4", ".mov", ".avi", ".mkv")):
                        z.write(os.path.join(batch_dir, fname), fname)
            print(f"    Created {zip_path}")
        else:
            print(f"  PROBLEM {bn}: NO ZIP and no batch folder")
            problems += 1
            continue
    
    # Verify ZIP contains matching files
    with zipfile.ZipFile(zip_path, "r") as zf:
        zip_names = [os.path.splitext(n)[0] for n in zf.namelist()]
    
    for cn in csv_names:
        if cn not in zip_names:
            print(f"  PROBLEM {bn}: CSV has '{cn}' but not in ZIP")
            problems += 1
    
    # Verify CSV fields
    for r in rows:
        issues = []
        if not r.get("categories_name", "").strip(): issues.append("NO_CAT")
        if not r.get("playlist_name", "").strip(): issues.append("NO_PLAYLIST")
        if not r.get("age_groups", "").strip(): issues.append("NO_AGE")
        if not r.get("channel_name", "").strip(): issues.append("NO_CHANNEL")
        if not r.get("language", "").strip(): issues.append("NO_LANG")
        if "," in r.get("categories_name", ""): issues.append("MULTI_CAT")
        if issues:
            print(f"  PROBLEM {bn}: {r.get('video_name','')[:35]} -> {' '.join(issues)}")
            problems += 1
    
    if problems == 0:
        zip_mb = os.path.getsize(zip_path) / (1024*1024)
        ready += 1
        print(f"  READY {bn}: {len(rows)} videos, {zip_mb:.1f} MB")

# Save cleaned batches.json
json.dump(b, open("batches.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)

pending = sum(1 for x in b.values() if x.get("status") == "pending_first_review" and not x.get("upload_failed"))
finalized = sum(1 for x in b.values() if x.get("status") == "finalized")

print(f"\n{'='*60}")
print(f"  {ready} READY | {problems} PROBLEMS | {fixed} flags cleared")
print(f"  Dashboard: {pending} Pending | {finalized} Finalized")
print(f"{'='*60}")
