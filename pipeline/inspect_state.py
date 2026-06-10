import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import STATE_FILE, BATCHES_DIR
STATE = STATE_FILE
with open(STATE, encoding='utf-8') as f:
    state = json.load(f)

# Get all batches referenced by retry_no_job_id failures
retry_batches = set()
for pid, rec in state.items():
    if rec.get('pipeline_status') == 'failed' and rec.get('failure_reason') == 'retry_no_job_id':
        if rec.get('batch'):
            retry_batches.add(rec['batch'])

print(f"Batches from retry_no_job_id failures: {len(retry_batches)}")
for b in sorted(retry_batches):
    zip_path = os.path.join(BATCHES_DIR, b + '.zip')
    exists = os.path.isfile(zip_path)
    print(f"  {b}: zip_exists={exists}")

print()
# Also check what zip files exist in batches dir
print("=== Zip files in batches/ dir ===")
if os.path.isdir(BATCHES_DIR):
    zips = [f for f in os.listdir(BATCHES_DIR) if f.endswith('.zip')]
    print(f"  Total: {len(zips)}")
    for z in sorted(zips):
        print(f"  {z}")
