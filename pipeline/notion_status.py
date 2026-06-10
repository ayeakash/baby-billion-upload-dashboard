import sys; sys.path.insert(0, '.')
import requests
from config import NOTION_TOKEN, NOTION_DATABASE_ID

headers = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28', 'Content-Type': 'application/json'}
counts = {}
cursor = None
while True:
    body = {'page_size': 100}
    if cursor: body['start_cursor'] = cursor
    r = requests.post(f'https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query', headers=headers, json=body)
    data = r.json()
    for p in data.get('results', []):
        s = (p.get('properties',{}).get('Status',{}).get('select') or {}).get('name','None')
        counts[s] = counts.get(s, 0) + 1
    if not data.get('has_more'): break
    cursor = data.get('next_cursor')

print('=== NOTION DATABASE ===')
for k,v in sorted(counts.items(), key=lambda x: -x[1]):
    print(f'  {k:30s}: {v}')
print(f'  TOTAL: {sum(counts.values())}')
