"""
Split mixed-category batches into single-category batches.
Regenerates CSVs, moves video files, and updates batches.json.
"""
import json, os, csv, shutil, sys

BATCHES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batches")
BATCHES_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batches.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))
from state_manager import next_batch_number

def run():
    # Load batches.json
    with open(BATCHES_JSON, "r", encoding="utf-8") as f:
        batches = json.load(f)

    # Find mixed-category batches by reading CSVs
    mixed = {}
    for csv_file in sorted(os.listdir(BATCHES_DIR)):
        if not csv_file.endswith(".csv"):
            continue
        bn = csv_file.replace(".csv", "")
        csv_path = os.path.join(BATCHES_DIR, csv_file)
        
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        
        cats = set(r.get("categories_name", "") for r in rows)
        if len(cats) > 1:
            mixed[bn] = {"csv_path": csv_path, "rows": rows, "cats": cats}
            print(f"  MIXED: {bn} has {len(cats)} categories: {cats}")

    if not mixed:
        print("No mixed-category batches found. All clean!")
        return

    # Process each mixed batch
    new_batch_count = sum(len(m["cats"]) for m in mixed.values())
    start_n = next_batch_number(count=new_batch_count)
    idx = 0

    for old_bn, info in mixed.items():
        print(f"\nSplitting {old_bn}...")
        old_csv = info["csv_path"]
        old_folder = os.path.join(BATCHES_DIR, old_bn)
        old_zip = os.path.join(BATCHES_DIR, f"{old_bn}.zip")
        
        # Group rows by category
        cat_groups = {}
        for row in info["rows"]:
            cat = row.get("categories_name", "Unknown")
            cat_groups.setdefault(cat, []).append(row)

        # Create new batches
        for cat, rows in sorted(cat_groups.items()):
            new_bn = f"Batch_{start_n + idx:02d}"
            idx += 1
            new_folder = os.path.join(BATCHES_DIR, new_bn)
            new_csv = os.path.join(BATCHES_DIR, f"{new_bn}.csv")
            os.makedirs(new_folder, exist_ok=True)

            # Copy video files
            for row in rows:
                fname = row.get("video_name", "")
                # Find the actual file in old folder
                for ext in [".mp4", ".webm", ".mkv", ".mov"]:
                    src = os.path.join(old_folder, fname + ext)
                    if os.path.isfile(src):
                        shutil.copy2(src, os.path.join(new_folder, fname + ext))
                        break

            # Write new CSV
            fieldnames = info["rows"][0].keys()
            with open(new_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            # Create batches.json entry from old batch data
            old_batch_data = batches.get(old_bn, {})
            new_batch = {
                "status": "pending_first_review",
                "created_at": old_batch_data.get("created_at", ""),
                "batch_size_bytes": sum(
                    os.path.getsize(os.path.join(new_folder, f))
                    for f in os.listdir(new_folder)
                    if os.path.isfile(os.path.join(new_folder, f))
                ),
                "upload_failed": False,
                "videos": [],
            }

            # Match videos from old batch
            for row in rows:
                vname = row.get("video_name", "")
                # Find matching video in old batch data
                matched = None
                if old_bn in batches:
                    for v in batches[old_bn].get("videos", []):
                        if v.get("video_name", "").startswith(vname) or vname in v.get("video_name", ""):
                            matched = dict(v)
                            break
                if matched:
                    matched["categories_name"] = cat
                    new_batch["videos"].append(matched)
                else:
                    new_batch["videos"].append({
                        "video_name": vname,
                        "categories_name": cat,
                        "page_id": "",
                        "pipeline_status": "batched",
                    })

            batches[new_bn] = new_batch
            print(f"  Created {new_bn}: {len(rows)} video(s), category='{cat}'")

        # Remove old batch
        if old_bn in batches:
            del batches[old_bn]
        if os.path.isfile(old_csv):
            os.remove(old_csv)
        if os.path.isdir(old_folder):
            shutil.rmtree(old_folder)
        if os.path.isfile(old_zip):
            os.remove(old_zip)
        print(f"  Removed old {old_bn}")

    # Save updated batches.json
    with open(BATCHES_JSON, "w", encoding="utf-8") as f:
        json.dump(batches, f, indent=2, ensure_ascii=False)

    print(f"\nDone! Split {len(mixed)} mixed batches into {idx} single-category batches.")

if __name__ == "__main__":
    run()
