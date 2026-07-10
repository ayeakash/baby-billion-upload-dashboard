"""Fix category names to match CMS exactly."""
import csv, os, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BATCHES_DIR = "batches"

# Corrections: old_name -> correct CMS name
FIXES = {
    "Paryayavachi Shabd": "Paryayvachi Shabd",
    "Birds": "Spot Colorful Birds",
    "Home items": "Home Items",
}

total_fixed = 0
for f in sorted(os.listdir(BATCHES_DIR)):
    if not f.endswith(".csv"):
        continue
    path = os.path.join(BATCHES_DIR, f)
    with open(path, "r", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    changed = False
    for r in rows:
        cat = r.get("categories_name", "").strip()
        if cat in FIXES:
            old = cat
            r["categories_name"] = FIXES[cat]
            changed = True
            total_fixed += 1
            print(f"  {f}: '{old}' -> '{FIXES[cat]}'")
    if changed:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)

print(f"\nFixed {total_fixed} rows")
