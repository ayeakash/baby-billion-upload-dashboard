"""
audit_cleanup.py — Audits pipeline state and deletes all files/batches
for videos that are marked 'uploaded' in state.json.
"""
import json, os, shutil, collections

STATE   = os.path.join(os.path.dirname(__file__), "state.json")
BATCHES = os.path.join(os.path.dirname(__file__), "batches")
DL_DIR  = os.path.join(os.path.dirname(__file__), "downloads")

with open(STATE, encoding="utf-8") as f:
    state = json.load(f)

# ── Status breakdown ──────────────────────────────────────────────────────────
counts = collections.Counter(rec.get("pipeline_status", "unknown") for rec in state.values())
print("=== STATE SUMMARY ===")
for s, n in sorted(counts.items()):
    print(f"  {s:20s}: {n}")
print(f"  {'TOTAL':20s}: {sum(counts.values())}")
print()

# ── Files still on disk by status ─────────────────────────────────────────────
print("=== FILES STILL ON DISK by status ===")
disk_by_status = collections.defaultdict(list)
for pid, rec in state.items():
    lf = rec.get("local_file", "")
    if lf and os.path.isfile(lf):
        disk_by_status[rec.get("pipeline_status", "unknown")].append(lf)

for s, files in sorted(disk_by_status.items()):
    print(f"  {s}: {len(files)} files on disk")
    for f in files[:5]:
        print(f"    {os.path.basename(f)}")
    if len(files) > 5:
        print(f"    ... and {len(files)-5} more")
print()

# ── Batch folders/CSVs still on disk ─────────────────────────────────────────
print("=== BATCH FOLDERS/CSVs STILL ON DISK (uploaded batches only) ===")
all_batches = set(rec.get("batch", "") for rec in state.values() if rec.get("batch"))
uploaded_batches = set(
    rec.get("batch", "")
    for rec in state.values()
    if rec.get("pipeline_status") == "uploaded" and rec.get("batch")
)
for b in sorted(all_batches):
    csv = os.path.join(BATCHES, f"{b}.csv")
    d   = os.path.join(BATCHES, b)
    status_set = set(rec.get("pipeline_status") for rec in state.values() if rec.get("batch") == b)
    csv_ok = os.path.isfile(csv)
    dir_ok = os.path.isdir(d)
    if (csv_ok or dir_ok) and b in uploaded_batches:
        print(f"  {b}: csv={csv_ok} dir={dir_ok}  statuses={status_set}")
print()

# ── Orphan files in downloads/ not tracked in state ───────────────────────────
if os.path.isdir(DL_DIR):
    all_dl = [os.path.join(DL_DIR, f) for f in os.listdir(DL_DIR) if os.path.isfile(os.path.join(DL_DIR, f))]
    state_files = set(rec.get("local_file", "") for rec in state.values())
    orphans = [f for f in all_dl if f not in state_files]
    print(f"=== ORPHAN files in downloads/ (not in state): {len(orphans)} ===")
    for f in orphans[:20]:
        print(f"  {os.path.basename(f)}")
print()

# ── CLEANUP: delete uploaded video files + their batch CSVs/dirs ─────────────
print("=== CLEANUP ===")
uploaded = {pid: rec for pid, rec in state.items() if rec.get("pipeline_status") == "uploaded"}
deleted_files = 0
already_gone  = 0
failed_files  = 0

for pid, rec in uploaded.items():
    lf = rec.get("local_file", "")
    if not lf:
        already_gone += 1
        continue
    if os.path.isfile(lf):
        try:
            os.remove(lf)
            print(f"  [DEL file] {os.path.basename(lf)}")
            deleted_files += 1
        except Exception as e:
            print(f"  [ERR file] {lf}: {e}")
            failed_files += 1
    else:
        already_gone += 1

deleted_csvs = 0
deleted_dirs = 0

for b in sorted(uploaded_batches):
    csv_path = os.path.join(BATCHES, f"{b}.csv")
    dir_path = os.path.join(BATCHES, b)
    if os.path.isfile(csv_path):
        try:
            os.remove(csv_path)
            print(f"  [DEL csv ] {b}.csv")
            deleted_csvs += 1
        except Exception as e:
            print(f"  [ERR csv ] {csv_path}: {e}")
    if os.path.isdir(dir_path):
        try:
            shutil.rmtree(dir_path)
            print(f"  [DEL dir ] {b}/")
            deleted_dirs += 1
        except Exception as e:
            print(f"  [ERR dir ] {dir_path}: {e}")

print()
print("=== CLEANUP SUMMARY ===")
print(f"  Video files deleted   : {deleted_files}")
print(f"  Video files already gone: {already_gone}")
print(f"  Video file errors     : {failed_files}")
print(f"  Batch CSVs deleted    : {deleted_csvs}")
print(f"  Batch dirs deleted    : {deleted_dirs}")
