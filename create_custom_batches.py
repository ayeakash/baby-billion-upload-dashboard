"""
create_custom_batches.py — Script to batch manually downloaded videos into upload-ready batches.
Division:
  1. Videos with date before 15th July -> Group 1
     - categories_name: Entertainment
     - playlist_name: ""
     - age_groups: ""
     - channel_name: AI_Cartoon_Stories_IG
     - language: Hindi
  2. Videos with date on/after 15th July -> Group 2
     - categories_name: Shivji
     - playlist_name: Stories
     - age_groups: 0-3, 3-6, 6+
     - channel_name: AI_Cartoon_Stories_IG
     - language: Hindi
"""

import os
import sys
import json
import re
import csv
import shutil
import zipfile
from datetime import datetime

# Include pipeline directory in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(BASE_DIR, "pipeline")
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import state_manager as sm

DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
BATCHES_DIR = os.path.join(BASE_DIR, "batches")
BATCHES_JSON = os.path.join(BASE_DIR, "batches.json")
STATE_JSON = os.path.join(BASE_DIR, "state.json")

MAX_BATCH_BYTES = 100 * 1024 * 1024  # 100 MB

CSV_HEADER = [
    "video_name", "categories_name", "age_groups", "channel_name",
    "tags", "playlist_name", "content_formats", "content_types", "language"
]

CHANNEL_NAME = "AI_Cartoon_Stories_IG"
CONTENT_TYPE = "Original"


def sanitize_video_name(filename: str) -> str:
    """Convert filename to clean video_name (no extension)."""
    name = os.path.splitext(filename)[0]
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s-]+', '_', name.strip())
    name = re.sub(r'_+', '_', name).strip('_')
    return name or "untitled"


def pack_files_by_size(file_list: list[str]) -> list[list[str]]:
    """Pack list of files into sub-100MB chunks."""
    batches = []
    curr_batch = []
    curr_size = 0

    for f in file_list:
        fpath = os.path.join(DOWNLOADS_DIR, f)
        fsize = os.path.getsize(fpath)

        if curr_batch and (curr_size + fsize) > MAX_BATCH_BYTES:
            batches.append(curr_batch)
            curr_batch = []
            curr_size = 0

        curr_batch.append(f)
        curr_size += fsize

    if curr_batch:
        batches.append(curr_batch)

    return batches


def main():
    os.makedirs(BATCHES_DIR, exist_ok=True)

    # Get all MP4 files from downloads/ (excluding empty/corrupt .mp4)
    all_files = sorted([
        f for f in os.listdir(DOWNLOADS_DIR)
        if f.lower().endswith(".mp4") and f != ".mp4"
    ])

    if not all_files:
        print("No MP4 files found in downloads/")
        return

    # Split into Group 1 (Before July 15) and Group 2 (On/After July 15)
    before_15 = []
    after_15 = []

    for f in all_files:
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', f)
        if m:
            month, day = int(m.group(2)), int(m.group(3))
            if month < 7 or (month == 7 and day < 15):
                before_15.append(f)
            else:
                after_15.append(f)
        else:
            before_15.append(f)

    # Metadata definitions per group
    meta_group1 = {
        "label": "Group 1 (Before 15th July)",
        "categories_name": "Entertainment",
        "playlist_name": "",
        "age_groups": "",
        "language": "Hindi"
    }

    meta_group2 = {
        "label": "Group 2 (On/After 15th July)",
        "categories_name": "Shivji",
        "playlist_name": "Stories",
        "age_groups": "0-3, 3-6, 6+",
        "language": "Hindi"
    }

    # Bin pack into sub-100MB batches
    group1_chunks = pack_files_by_size(before_15)
    group2_chunks = pack_files_by_size(after_15)

    all_chunks = []
    for chunk in group1_chunks:
        all_chunks.append((meta_group1, chunk))
    for chunk in group2_chunks:
        all_chunks.append((meta_group2, chunk))

    total_batches = len(all_chunks)

    # Start at Batch_05
    start_batch_num = 5

    # Clean up old custom batch folders / zip / csv files if re-running
    for n in range(5, 5 + total_batches + 5):
        bname = f"Batch_{n:02d}"
        bdir = os.path.join(BATCHES_DIR, bname)
        bcsv = os.path.join(BATCHES_DIR, f"{bname}.csv")
        bzip = os.path.join(BATCHES_DIR, f"{bname}.zip")
        if os.path.isdir(bdir):
            shutil.rmtree(bdir)
        if os.path.isfile(bcsv):
            os.remove(bcsv)
        if os.path.isfile(bzip):
            os.remove(bzip)

    print(f"\n============================================================")
    print(f"  Batching {len(all_files)} videos into {total_batches} upload-ready batches")
    print(f"  Group 1 (Before 15th July): {len(before_15)} videos in {len(group1_chunks)} batch(es)")
    print(f"  Group 2 (On/After 15th July): {len(after_15)} videos in {len(group2_chunks)} batch(es)")
    print(f"  Starting Batch Number: Batch_{start_batch_num:02d}")
    print(f"============================================================\n")

    # Load existing batches.json
    batches_json_data = {}
    if os.path.isfile(BATCHES_JSON):
        try:
            with open(BATCHES_JSON, "r", encoding="utf-8") as f:
                batches_json_data = json.load(f)
        except Exception as e:
            print(f"Warning loading batches.json: {e}")

    # Remove previous Batch_05+ entries to allow clean overwrite
    for key in list(batches_json_data.keys()):
        m = re.match(r'Batch_(\d+)', key)
        if m and int(m.group(1)) >= start_batch_num:
            del batches_json_data[key]

    # Load existing state.json
    state_json_data = {}
    if os.path.isfile(STATE_JSON):
        try:
            with open(STATE_JSON, "r", encoding="utf-8") as f:
                state_json_data = json.load(f)
        except Exception as e:
            print(f"Warning loading state.json: {e}")

    # Remove previous manual_Batch_05+ entries from state.json
    for key in list(state_json_data.keys()):
        if key.startswith("manual_Batch_"):
            m = re.match(r'manual_Batch_(\d+)', key)
            if m and int(m.group(1)) >= start_batch_num:
                del state_json_data[key]

    # Update batch counter in state metadata
    meta = state_json_data.setdefault("_meta", {})
    meta["batch_counter"] = start_batch_num + total_batches - 1

    created_batches = []

    for idx, (meta_info, chunk_files) in enumerate(all_chunks):
        batch_num = start_batch_num + idx
        batch_name = f"Batch_{batch_num:02d}"
        batch_dir = os.path.join(BATCHES_DIR, batch_name)
        batch_csv = os.path.join(BATCHES_DIR, f"{batch_name}.csv")
        batch_zip = os.path.join(BATCHES_DIR, f"{batch_name}.zip")

        os.makedirs(batch_dir, exist_ok=True)

        batch_videos_info = []
        csv_rows = []

        total_size = sum(os.path.getsize(os.path.join(DOWNLOADS_DIR, f)) for f in chunk_files)
        total_mb = total_size / (1024 * 1024)

        group_label = meta_info["label"]
        cat_name = meta_info["categories_name"]
        playlist_name = meta_info["playlist_name"]
        age_grps = meta_info["age_groups"]
        lang = meta_info["language"]

        print(f"  Creating [{batch_name}] ({group_label}): {len(chunk_files)} videos, {total_mb:.1f} MB")
        print(f"      Category: '{cat_name}', Playlist: '{playlist_name}', Age: '{age_grps}'")

        for i, fname in enumerate(chunk_files):
            src_path = os.path.join(DOWNLOADS_DIR, fname)
            vstem = sanitize_video_name(fname)
            clean_fname = f"{vstem}.mp4"
            dst_path = os.path.join(batch_dir, clean_fname)

            # Copy file to batch dir
            if not os.path.exists(dst_path):
                shutil.copy2(src_path, dst_path)

            # CSV Row
            row = {
                "video_name": vstem,
                "categories_name": cat_name,
                "age_groups": age_grps,
                "channel_name": CHANNEL_NAME,
                "tags": "",
                "playlist_name": playlist_name,
                "content_formats": "",
                "content_types": CONTENT_TYPE,
                "language": lang,
            }
            csv_rows.append(row)

            # Video metadata for batches.json / state.json
            page_id = f"manual_{batch_name}_{i}"
            video_rec = {
                "page_id": page_id,
                "video_name": vstem,
                "age_group": age_grps,
                "category": cat_name,
                "playlist": playlist_name,
                "channel": CHANNEL_NAME,
                "local_file": dst_path,
                "drive_link": "",
                "pipeline_status": "batched",
                "language": lang,
                "source_file": fname
            }
            batch_videos_info.append(video_rec)

            # Register in state_json_data
            state_json_data[page_id] = {
                "page_id": page_id,
                "video_name": vstem,
                "age_group": age_grps,
                "category": cat_name,
                "playlist": playlist_name,
                "channel": CHANNEL_NAME,
                "pipeline_status": "batched",
                "batch": batch_name,
                "source": "manual_download",
                "local_file": dst_path,
                "updated_at": datetime.now().isoformat(),
            }

        # Write CSV
        with open(batch_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
            writer.writeheader()
            writer.writerows(csv_rows)

        # Create ZIP
        print(f"           Zipping into {batch_name}.zip...")
        with zipfile.ZipFile(batch_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in os.listdir(batch_dir):
                if fname.lower().endswith(".mp4"):
                    file_p = os.path.join(batch_dir, fname)
                    zf.write(file_p, fname)

        # Register batch in batches.json
        batches_json_data[batch_name] = {
            "batch_name": batch_name,
            "status": "pending_first_review",
            "created_at": datetime.now().isoformat(),
            "source": "manual_download",
            "group_label": group_label,
            "videos": batch_videos_info,
            "upload_job_id": None,
            "upload_date": None,
            "upload_completed": False,
            "upload_failed": False,
            "fail_reason": None,
            "finalized_date": None,
        }

        created_batches.append((batch_name, group_label, len(chunk_files), total_mb, cat_name, playlist_name, age_grps))
        print(f"           ✅ {batch_name} created successfully!")

    # Save batches.json
    tmp_bj = BATCHES_JSON + ".tmp"
    with open(tmp_bj, "w", encoding="utf-8") as f:
        json.dump(batches_json_data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_bj, BATCHES_JSON)

    # Save state.json
    tmp_sj = STATE_JSON + ".tmp"
    with open(tmp_sj, "w", encoding="utf-8") as f:
        json.dump(state_json_data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_sj, STATE_JSON)

    print(f"\n============================================================")
    print(f"  All batches created and registered successfully!")
    for bname, label, count, size_mb, cat, pl, age in created_batches:
        print(f"  - {bname} ({label}): {count} vids, {size_mb:.1f} MB | Cat: '{cat}', PL: '{pl}', Age: '{age}'")
    print(f"============================================================\n")


if __name__ == "__main__":
    main()
