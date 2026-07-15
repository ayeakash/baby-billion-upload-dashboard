"""
batch_downloads.py — Create upload-ready batches from downloaded videos.
Groups videos into ~100MB batches with CSV + directory + ZIP.
"""
import csv
import os
import re
import shutil
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "youtube", "downloads")
BATCHES_DIR = os.path.join(BASE_DIR, "batches")
MAX_BATCH_BYTES = 100 * 1024 * 1024  # 100 MB

CSV_HEADER = [
    "video_name", "categories_name", "age_groups", "channel_name",
    "tags", "playlist_name", "content_formats", "content_types", "language"
]


def get_next_batch_number() -> int:
    """Find the highest existing batch number and return next."""
    max_num = 0
    if os.path.isdir(BATCHES_DIR):
        for name in os.listdir(BATCHES_DIR):
            m = re.match(r"Batch_(\d+)", name)
            if m:
                max_num = max(max_num, int(m.group(1)))
    return max_num + 1


def sanitize_video_name(filename: str) -> str:
    """Convert filename to video_name (no extension)."""
    name = os.path.splitext(filename)[0]
    # Replace spaces with underscores, remove non-safe chars
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s-]+', '_', name.strip())
    name = re.sub(r'_+', '_', name).strip('_')
    return name


def main():
    # Get all MP4 files sorted by name
    files = sorted([
        f for f in os.listdir(DOWNLOAD_DIR)
        if f.lower().endswith(".mp4")
    ])

    if not files:
        print("  No MP4 files found in youtube/downloads/")
        return

    print(f"\n  Found {len(files)} MP4 files to batch")
    print(f"  Max batch size: {MAX_BATCH_BYTES // (1024*1024)} MB\n")

    # Group into batches by size
    batches = []
    current_batch = []
    current_size = 0

    for f in files:
        fpath = os.path.join(DOWNLOAD_DIR, f)
        fsize = os.path.getsize(fpath)

        if current_batch and (current_size + fsize) > MAX_BATCH_BYTES:
            batches.append(current_batch)
            current_batch = []
            current_size = 0

        current_batch.append((f, fpath, fsize))
        current_size += fsize

    if current_batch:
        batches.append(current_batch)

    next_num = get_next_batch_number()
    print(f"  Creating {len(batches)} batches (starting at Batch_{next_num:02d})\n")

    for i, batch_files in enumerate(batches):
        batch_num = next_num + i
        batch_name = f"Batch_{batch_num:02d}"
        batch_dir = os.path.join(BATCHES_DIR, batch_name)
        batch_csv = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
        batch_zip = os.path.join(BATCHES_DIR, f"{batch_name}.zip")

        batch_size = sum(s for _, _, s in batch_files)
        print(f"  [{batch_name}] {len(batch_files)} videos, {batch_size / (1024*1024):.1f} MB")

        # Create batch directory
        os.makedirs(batch_dir, exist_ok=True)

        # Copy files and build CSV rows
        csv_rows = []
        for fname, fpath, _ in batch_files:
            # Copy video to batch dir
            dest = os.path.join(batch_dir, fname)
            if not os.path.exists(dest):
                shutil.copy2(fpath, dest)

            video_name = sanitize_video_name(fname)
            csv_rows.append({
                "video_name": video_name,
                "categories_name": "Entertainment",
                "age_groups": "",
                "channel_name": "BabyBillion",
                "tags": "",
                "playlist_name": "",
                "content_formats": "",
                "content_types": "Original",
                "language": "English",
            })

        # Write CSV
        with open(batch_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
            writer.writeheader()
            for row in csv_rows:
                writer.writerow(row)

        # Create ZIP
        print(f"           Zipping...")
        with zipfile.ZipFile(batch_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, _, _ in batch_files:
                src = os.path.join(batch_dir, fname)
                zf.write(src, fname)

        print(f"           ✅ Done")

    print(f"\n  ============================================================")
    print(f"   Created {len(batches)} batches (Batch_{next_num:02d} → Batch_{next_num + len(batches) - 1:02d})")
    print(f"  ============================================================\n")


if __name__ == "__main__":
    main()
