"""
create_batch_12_csv.py -- Create Batch_12.csv with the 37 remaining videos.
"""

import csv
from pathlib import Path
from config import BATCHES_DIR

# Find original CSV
original_csv = None
for f in Path(BATCHES_DIR).glob("Stories_Entertainment_*.csv"):
    original_csv = f
    break

if not original_csv:
    print("Original CSV not found")
    exit(1)

print(f"Using original CSV: {original_csv.name}")

# Get video names from Batches 1-7
batched_videos = set()
batches_dir = Path(BATCHES_DIR) / "Stories_Batches"

for i in range(1, 8):
    csv_file = batches_dir / f"Batch_{i:02d}.csv"
    if csv_file.exists():
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                video_name = row.get("video_name", "").strip()
                if video_name:
                    batched_videos.add(video_name)

print(f"Already batched: {len(batched_videos)} videos")

# Extract remaining videos
remaining_rows = []
with open(original_csv, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    header = reader.fieldnames
    for row in reader:
        video_name = row.get("video_name", "").strip()
        if video_name and video_name not in batched_videos:
            remaining_rows.append(row)

print(f"Remaining: {len(remaining_rows)} videos")

# Create Batch_12.csv
batch_12_csv = batches_dir / "Batch_12.csv"
with open(batch_12_csv, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=header)
    writer.writeheader()
    writer.writerows(remaining_rows)

print(f"Created: {batch_12_csv.name}")
