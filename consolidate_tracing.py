import os, csv, shutil, zipfile, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BATCHES_DIR = r"d:\BabyBillion\upload_dashboard\batches"
SOURCE = os.path.join(BATCHES_DIR, "Batch_956")
SOURCE_CSV = os.path.join(BATCHES_DIR, "Batch_956.csv")

CSV_HEADER = ["video_name","categories_name","age_groups","channel_name","tags","playlist_name","content_formats","content_types","language"]

# Read existing CSV to preserve per-video metadata
video_meta = {}
with open(SOURCE_CSV, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        video_meta[row["video_name"]] = row

# Get sorted video files
videos = sorted([f for f in os.listdir(SOURCE) if f.lower().endswith('.mp4')])
print(f"Total videos: {len(videos)}")

# Split: 20, 19, remaining
splits = [20, 19]
chunks = []
idx = 0
for s in splits:
    chunks.append(videos[idx:idx+s])
    idx += s
if idx < len(videos):
    chunks.append(videos[idx:])

# Create batches starting from 956 (replacing it)
for i, chunk in enumerate(chunks):
    batch_num = 956 + i
    batch_name = f"Batch_{batch_num}"
    batch_dir = os.path.join(BATCHES_DIR, batch_name)
    batch_csv = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
    batch_zip = os.path.join(BATCHES_DIR, f"{batch_name}.zip")

    os.makedirs(batch_dir, exist_ok=True)

    rows = []
    for f in chunk:
        name = os.path.splitext(f)[0]
        src = os.path.join(SOURCE, f)
        dst = os.path.join(batch_dir, f)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
        meta = video_meta.get(name, {})
        rows.append([
            name,
            meta.get("categories_name", "Write Your Numbers"),
            meta.get("age_groups", "3-6"),
            meta.get("channel_name", "BabyBillion_Education"),
            meta.get("tags", ""),
            meta.get("playlist_name", "English Fluency"),
            meta.get("content_formats", ""),
            meta.get("content_types", "Original"),
            meta.get("language", "English"),
        ])

    with open(batch_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)

    with zipfile.ZipFile(batch_zip, 'w', zipfile.ZIP_STORED) as zf:
        for vf in chunk:
            zf.write(os.path.join(batch_dir, vf), vf)
    
    zip_mb = os.path.getsize(batch_zip) / (1024*1024)
    print(f"{batch_name}: {len(chunk)} videos, {zip_mb:.1f} MB ZIP")

# Clean up original Batch_956 folder (now split into new batches)
# The first chunk reused Batch_956 dir, so we just need to remove extra files
# Actually let's clean properly: remove files not in chunk 0 from Batch_956
chunk0_files = set(chunks[0])
for f in os.listdir(os.path.join(BATCHES_DIR, "Batch_956")):
    if f not in chunk0_files:
        os.remove(os.path.join(BATCHES_DIR, "Batch_956", f))

# Remove old zip
old_zip = os.path.join(BATCHES_DIR, "Batch_956.zip")
if os.path.exists(old_zip):
    os.remove(old_zip)

# Recreate Batch_956 zip with only its videos
with zipfile.ZipFile(old_zip, 'w', zipfile.ZIP_STORED) as zf:
    for vf in chunks[0]:
        zf.write(os.path.join(BATCHES_DIR, "Batch_956", vf), vf)
zip_mb = os.path.getsize(old_zip) / (1024*1024)
print(f"\nBatch_956 ZIP recreated: {zip_mb:.1f} MB")

print("\nDONE!")
