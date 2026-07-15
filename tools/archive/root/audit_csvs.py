"""Full audit of all CSVs + check which failed on CMS."""
import csv, os, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BATCHES_DIR = "batches"

# CMS FAILED batch IDs from screenshots
cms_failed_ids = {
    "d04d7af8-413c-4a7a-9699-851bc4a00a21",
    "38e82f61-4055-4ef4-a827-eff73c228488",
    "c28fb891-f5de-4dad-9122-5308d1c90322",
    "cb8ce178-2cf6-4aea-9339-7a49aba6ad79",
    "08996182-eca0-491e-b0a5-7b0e303783cb",
    "d203b9f9-9916-4a81-a334-26208dcd18d5",
    "46da1f8f-10f0-4aff-9c7a-244347f04b07",
    "9025840a-f4d6-4b84-8ac1-5f51ba6847f0a",
    "2788fced-bbca-4aba-bee0-9945b122c531",
    "3e28a751-fc77-478b-9f78-500ed2f53315",
    "6268be96-408f-4053-93ee-012528211fbe",
    "d6f6b6ac-0c77-44b0-9f4e-60f5e0d2f183",
}

# Load batches.json to map batch names to CMS job IDs
import json
batches = json.load(open("batches.json", "r", encoding="utf-8"))

print("=" * 100)
print("PART 1: CSV VALIDATION")
print("=" * 100)
total_ok = 0
total_bad = 0
for f in sorted(os.listdir(BATCHES_DIR)):
    if not f.endswith(".csv"):
        continue
    path = os.path.join(BATCHES_DIR, f)
    with open(path, "r", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        issues = []
        if not r.get("categories_name", "").strip(): issues.append("NO_CAT")
        if not r.get("age_groups", "").strip(): issues.append("NO_AGE")
        if not r.get("language", "").strip(): issues.append("NO_LANG")
        if not r.get("playlist_name", "").strip(): issues.append("NO_PLAYLIST")
        if not r.get("channel_name", "").strip(): issues.append("NO_CHANNEL")
        if "," in r.get("categories_name", ""): issues.append("MULTI_CAT")
        if issues:
            total_bad += 1
            print(f"  BAD: {f:20s} {r.get('video_name','')[:40]:40s} {' '.join(issues)}")
        else:
            total_ok += 1

print(f"\n  Result: {total_ok} OK, {total_bad} BAD\n")

print("=" * 100)
print("PART 2: CMS-FAILED BATCHES - Why did they fail?")
print("=" * 100)

# Map job_id -> batch_name
jid_to_batch = {}
for bn, data in batches.items():
    jid = data.get("upload_job_id", "")
    if jid:
        jid_to_batch[jid] = bn

for jid in sorted(cms_failed_ids):
    bn = jid_to_batch.get(jid, "???")
    csv_path = os.path.join(BATCHES_DIR, f"{bn}.csv")
    zip_path = os.path.join(BATCHES_DIR, f"{bn}.zip")
    
    has_csv = os.path.isfile(csv_path)
    has_zip = os.path.isfile(zip_path)
    
    csv_issues = []
    video_names = []
    if has_csv:
        with open(csv_path, "r", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            vn = r.get("video_name", "")
            video_names.append(vn)
            if not r.get("categories_name", ""): csv_issues.append(f"{vn}: NO_CAT")
            if not r.get("playlist_name", ""): csv_issues.append(f"{vn}: NO_PLAYLIST")
            if "," in r.get("categories_name", ""): csv_issues.append(f"{vn}: MULTI_CAT")
    
    # Check if ZIP contains the right files
    zip_issues = []
    if has_zip:
        import zipfile
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zip_files = [os.path.splitext(n)[0] for n in zf.namelist()]
                for vn in video_names:
                    if vn not in zip_files:
                        zip_issues.append(f"MISSING in ZIP: {vn}")
                zip_size_mb = os.path.getsize(zip_path) / (1024*1024)
        except Exception as e:
            zip_issues.append(f"ZIP ERROR: {e}")
            zip_size_mb = 0
    else:
        zip_size_mb = 0
    
    status = "CSV issues" if csv_issues else ("ZIP issues" if zip_issues else "CSV+ZIP look OK")
    
    print(f"\n  {bn} (Job: {jid[:16]}...)")
    print(f"    CSV: {'YES' if has_csv else 'NO'} | ZIP: {'YES' if has_zip else 'NO'} ({zip_size_mb:.1f} MB)")
    print(f"    Videos: {', '.join(v[:30] for v in video_names[:3])}")
    if csv_issues:
        print(f"    CSV PROBLEMS: {'; '.join(csv_issues[:3])}")
    elif zip_issues:
        print(f"    ZIP PROBLEMS: {'; '.join(zip_issues[:3])}")
    else:
        print(f"    STATUS: CSV+ZIP look correct — CMS may have rejected for other reason (duplicate video name on platform?)")
