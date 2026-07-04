"""
fix_reupload_batches.py — Fix existing re-upload batch CSVs.

Removes redundant _Hindi / _English suffixes from video names
that already have ___ln_Hi / ___ln_En language tags.

Usage:
    python fix_reupload_batches.py [--dry-run]
"""
import csv
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
REUPLOAD_DIR = os.path.join(PROJECT_ROOT, "re-upload batches")

# Pattern: ___ln_Hi_Hindi or ___ln_En_English at end of video_name
# We want to strip the _Hindi or _English part
REDUNDANT_LANG_PATTERN = re.compile(
    r"(___ln_Hi)_Hindi$|(___ln_En)_English$",
    re.IGNORECASE
)


def fix_video_name(name: str) -> str:
    """Remove redundant _Hindi/_English after ___ln_Hi/___ln_En."""
    # Handle case-insensitive variants
    m = REDUNDANT_LANG_PATTERN.search(name)
    if m:
        if m.group(1):  # ___ln_Hi_Hindi
            return name[:m.start()] + m.group(1)
        elif m.group(2):  # ___ln_En_English
            return name[:m.start()] + m.group(2)
    return name


def main():
    dry_run = "--dry-run" in sys.argv

    if not os.path.isdir(REUPLOAD_DIR):
        print(f"Directory not found: {REUPLOAD_DIR}")
        sys.exit(1)

    csv_files = sorted([
        f for f in os.listdir(REUPLOAD_DIR)
        if f.endswith(".csv") and f.startswith("Batch_")
    ])

    print(f"Found {len(csv_files)} batch CSV files in: {REUPLOAD_DIR}")
    if dry_run:
        print("[DRY RUN] — showing changes without writing\n")

    total_fixed = 0
    files_changed = 0

    for csv_file in csv_files:
        csv_path = os.path.join(REUPLOAD_DIR, csv_file)
        rows = []
        changed = False

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                old_name = row.get("video_name", "")
                new_name = fix_video_name(old_name)
                if new_name != old_name:
                    if dry_run:
                        print(f"  [{csv_file}] {old_name}")
                        print(f"         -> {new_name}")
                    row["video_name"] = new_name
                    changed = True
                    total_fixed += 1
                rows.append(row)

        if changed:
            files_changed += 1
            if not dry_run:
                with open(csv_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                print(f"  [FIXED] {csv_file}")

    print(f"\n{'='*60}")
    print(f"  Total video names fixed: {total_fixed}")
    print(f"  Batch files modified:    {files_changed}")
    if dry_run:
        print(f"  [DRY RUN] No files were actually modified")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
