"""Check if non-uploaded videos in state.json are wrongly marked as Uploaded in Notion."""
import json, requests
from config import NOTION_TOKEN, NOTION_DATABASE_ID, PROP_UPLOAD

state = json.load(open("state.json", "r", encoding="utf-8"))
headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

non_uploaded = [(pid, rec) for pid, rec in state.items() if rec.get("pipeline_status") != "uploaded"]
print(f"Checking {len(non_uploaded)} non-uploaded videos against Notion...\n")

wrong = 0
ok = 0
errors = 0
for pid, rec in non_uploaded:
    try:
        r = requests.get(f"https://api.notion.com/v1/pages/{pid}", headers=headers, timeout=15)
        if r.status_code != 200:
            errors += 1
            continue
        props = r.json().get("properties", {})
        upload_prop = props.get(PROP_UPLOAD, {})
        t = upload_prop.get("type", "")
        if t == "checkbox":
            is_uploaded = upload_prop.get("checkbox", False)
        elif t == "select":
            sel = upload_prop.get("select")
            is_uploaded = (sel["name"].lower() == "yes") if sel else False
        else:
            is_uploaded = False

        name = rec.get("video_name", "?")
        status = rec.get("pipeline_status", "?")
        if is_uploaded:
            wrong += 1
            print(f"  [WRONG] {name:50s} state={status:15s} Notion=Uploaded")
        else:
            ok += 1
    except Exception as e:
        errors += 1
        print(f"  [ERR] {pid}: {e}")

print(f"\n=== RESULT ===")
print(f"  Wrongly marked uploaded in Notion: {wrong}")
print(f"  Correctly NOT uploaded in Notion:  {ok}")
print(f"  Errors checking:                   {errors}")
