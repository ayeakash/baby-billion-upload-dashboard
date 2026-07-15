"""Mark bad_category failed videos as 'Failed' in Notion."""
import json, time, requests
from config import NOTION_TOKEN, PROP_STATUS

state = json.load(open("state.json", "r", encoding="utf-8"))
failed = [
    (pid, rec) for pid, rec in state.items()
    if isinstance(rec, dict)
    and rec.get("pipeline_status") == "failed"
    and rec.get("failure_reason", "").startswith("bad_category")
]

print(f"Marking {len(failed)} videos as failed in Notion...")

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}
done = 0
err = 0
for pid, rec in failed:
    patch = {"properties": {PROP_STATUS: {"select": {"name": "Failed"}}}}
    try:
        r = requests.patch(
            f"https://api.notion.com/v1/pages/{pid}",
            headers=headers, json=patch, timeout=15
        )
        if r.status_code == 200:
            done += 1
        else:
            err += 1
            name = rec.get("video_name", "?")
            print(f"  [ERR] {name}: HTTP {r.status_code}")
    except Exception as e:
        err += 1
        name = rec.get("video_name", "?")
        print(f"  [ERR] {name}: {e}")
    if done % 20 == 0 and done > 0:
        print(f"  ... {done}/{len(failed)}")
    time.sleep(0.35)

print(f"\nDone: {done}, Errors: {err}")
