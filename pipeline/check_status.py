import json, collections, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import STATE_FILE
STATE = STATE_FILE
with open(STATE, encoding='utf-8') as f:
    state = json.load(f)

counts = collections.Counter(rec.get('pipeline_status','unknown') for rec in state.values())
print('=== STATUS SUMMARY ===')
for s, n in sorted(counts.items()):
    print(f'  {s:20s}: {n}')
print(f'  {"TOTAL":20s}: {sum(counts.values())}')

print()
print('=== FAILURES ===')
for pid, rec in state.items():
    if rec.get('pipeline_status') == 'failed':
        name   = rec.get('video_name', '?')
        reason = rec.get('failure_reason', '?')
        print(f'  {name:45s}  reason: {reason}')
