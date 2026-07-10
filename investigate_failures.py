"""Map CMS screenshot failures to dashboard batches and analyze root cause."""
import json, os, io, sys, csv as csv_mod, zipfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BATCHES_DIR = "batches"

# From the CMS screenshot (newest first)
cms_results = [
    ("9bc7fb33", "FAILED",    0),  # was 9bcc7fb33 in screenshot
    ("65997746", "FAILED",    0),
    ("6a51511b", "COMPLETED", 1),
    ("498ac325", "FAILED",    0),
    ("903245e2", "FAILED",    0),
    ("4b116127", "FAILED",    0),
    ("4c19770b", "FAILED",    0),
    ("47cd4529", "FAILED",    0),
    ("a2db8c44", "COMPLETED", 2),
    ("62a26f69", "COMPLETED", 2),
    ("a89c7ee1", "FAILED",    0),
    ("c4ae88f4", "FAILED",    0),
    ("ace86daa", "FAILED",    0),
    ("982d4c25", "FAILED",    0),
    ("1c0d68a1", "COMPLETED", 1),
]

# Load history to map job_id -> batch_name
history = [json.loads(l) for l in open("upload_history.jsonl", encoding="utf-8")]
jid_to_batch = {}
for e in history:
    jid = e.get("job_id", "")
    bn = e.get("batch_name", "")
    if jid and bn:
        jid_to_batch[jid[:8]] = bn

print("CMS FAILED batches - investigating root cause:")
print("=" * 100)

for jid_short, status, total in cms_results:
    if status != "FAILED":
        continue
    
    bn = jid_to_batch.get(jid_short, "???")
    csv_path = os.path.join(BATCHES_DIR, f"{bn}.csv")
    zip_path = os.path.join(BATCHES_DIR, f"{bn}.zip")
    
    print(f"\n  {bn} (CMS: {jid_short}... FAILED, {total} total)")
    
    if not os.path.isfile(csv_path):
        print(f"    NO CSV on disk!")
        continue
    
    # Read CSV
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv_mod.DictReader(f))
    
    print(f"    CSV: {len(rows)} rows")
    for r in rows:
        vn = r.get("video_name", "")
        cat = r.get("categories_name", "")
        pl = r.get("playlist_name", "")
        age = r.get("age_groups", "")
        ch = r.get("channel_name", "")
        lang = r.get("language", "")
        ct = r.get("content_types", "")
        cf = r.get("content_formats", "")
        print(f"      {vn[:35]:35s} cat={cat:25s} pl={pl:18s} age={age:5s} ch={ch:22s} lang={lang} ct={ct} cf={cf}")
    
    # Check ZIP
    if os.path.isfile(zip_path):
        with zipfile.ZipFile(zip_path, "r") as zf:
            zip_names = [os.path.splitext(n)[0] for n in zf.namelist()]
            zip_size = os.path.getsize(zip_path) / (1024*1024)
        
        # Check if CSV video_names match ZIP filenames
        csv_names = [r.get("video_name", "") for r in rows]
        mismatches = []
        for cn in csv_names:
            if cn not in zip_names:
                mismatches.append(cn)
        if mismatches:
            print(f"    ZIP MISMATCH: {mismatches}")
        else:
            print(f"    ZIP OK: {zip_size:.1f} MB, {len(zip_names)} files, names match CSV")
    else:
        print(f"    NO ZIP on disk!")
