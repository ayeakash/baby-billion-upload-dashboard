import os
import sys
import json
import re
import csv
import shutil
import zipfile
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_DIR = os.path.join(BASE_DIR, "pipeline")
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import compressor
import state_manager as sm

SRC_FILE = os.path.join(BASE_DIR, "downloads", "Classic_Tenali_The_Three_Tests(08).mp4")
BATCHES_DIR = os.path.join(BASE_DIR, "batches")
BATCHES_JSON = os.path.join(BASE_DIR, "batches.json")
STATE_JSON = os.path.join(BASE_DIR, "state.json")

CSV_HEADER = [
    "video_name", "categories_name", "age_groups", "channel_name",
    "tags", "playlist_name", "content_formats", "content_types", "language"
]

def run():
    print(f"--- Processing {SRC_FILE} ---")
    if not os.path.isfile(SRC_FILE):
        print(f"Error: Source file {SRC_FILE} does not exist!")
        return

    orig_size = os.path.getsize(SRC_FILE) / (1024 * 1024)
    print(f"Original File Size: {orig_size:.2f} MB")

    batch_name = "Batch_10"
    batch_dir = os.path.join(BATCHES_DIR, batch_name)
    os.makedirs(batch_dir, exist_ok=True)

    vstem = "Classic_Tenali_The_Three_Tests_08"
    dst_mp4 = os.path.join(batch_dir, f"{vstem}.mp4")

    # Step 1: Copy to batch folder
    print(f"Copying file to {dst_mp4}...")
    shutil.copy2(SRC_FILE, dst_mp4)

    # Step 2: Compress video
    print("Compressing video using FFmpeg compressor...")
    compressed_path = compressor.compress(page_id="manual_Batch_10_0", video_name=vstem, local_file=dst_mp4)
    
    comp_size = os.path.getsize(dst_mp4) / (1024 * 1024)
    print(f"Compressed File Size: {comp_size:.2f} MB")

    # Step 3: Create CSV
    batch_csv = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
    row = {
        "video_name": vstem,
        "categories_name": "Tenali",
        "age_groups": "0-3",
        "channel_name": "AI_Cartoon_Stories_IG",
        "tags": "",
        "playlist_name": "Stories",
        "content_formats": "",
        "content_types": "Original",
        "language": "Hindi",
    }

    with open(batch_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerow(row)
    print(f"Created CSV: {batch_csv}")

    # Step 4: Create ZIP
    batch_zip = os.path.join(BATCHES_DIR, f"{batch_name}.zip")
    with zipfile.ZipFile(batch_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(dst_mp4, f"{vstem}.mp4")
    print(f"Created ZIP: {batch_zip}")

    # Step 5: Update batches.json
    batches_data = {}
    if os.path.isfile(BATCHES_JSON):
        with open(BATCHES_JSON, "r", encoding="utf-8") as f:
            batches_data = json.load(f)

    page_id = "manual_Batch_10_0"
    video_rec = {
        "page_id": page_id,
        "video_name": vstem,
        "age_group": "0-3",
        "category": "Tenali",
        "playlist": "Stories",
        "channel": "AI_Cartoon_Stories_IG",
        "local_file": dst_mp4,
        "drive_link": "",
        "pipeline_status": "batched",
        "language": "Hindi",
        "source_file": os.path.basename(SRC_FILE)
    }

    batches_data[batch_name] = {
        "batch_name": batch_name,
        "status": "pending_first_review",
        "created_at": datetime.now().isoformat(),
        "source": "manual_download",
        "group_label": "Custom Single Batch",
        "videos": [video_rec],
        "upload_job_id": None,
        "upload_date": None,
        "upload_completed": False,
        "upload_failed": False,
        "fail_reason": None,
        "finalized_date": None
    }

    tmp_bj = BATCHES_JSON + ".tmp"
    with open(tmp_bj, "w", encoding="utf-8") as f:
        json.dump(batches_data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_bj, BATCHES_JSON)
    print(f"Updated {BATCHES_JSON}")

    # Step 6: Update state.json
    state_data = {}
    if os.path.isfile(STATE_JSON):
        with open(STATE_JSON, "r", encoding="utf-8") as f:
            state_data = json.load(f)

    state_data[page_id] = {
        "page_id": page_id,
        "video_name": vstem,
        "age_group": "0-3",
        "category": "Tenali",
        "playlist": "Stories",
        "channel": "AI_Cartoon_Stories_IG",
        "pipeline_status": "batched",
        "batch": batch_name,
        "source": "manual_download",
        "local_file": dst_mp4,
        "updated_at": datetime.now().isoformat()
    }

    meta = state_data.setdefault("_meta", {})
    meta["batch_counter"] = max(meta.get("batch_counter", 0), 10)

    tmp_sj = STATE_JSON + ".tmp"
    with open(tmp_sj, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_sj, STATE_JSON)
    print(f"Updated {STATE_JSON}")

    print(f"\n✅ {batch_name} created & batched successfully!")

if __name__ == "__main__":
    run()
