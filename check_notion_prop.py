import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "pipeline"))
import json
import notion_client as nc

batches = json.load(open("batches.json", encoding="utf-8"))
b = batches.get("Batch_601", {})
videos = [v for v in b.get("videos", []) if v.get("pipeline_status") != "bad"]
print(f"Syncing {len(videos)} videos to Notion (Draft Upload)...")
for v in videos:
    pid = v["page_id"]
    vn = v["video_name"]
    lang = "___ln_Hi" if "___ln_Hi" in vn else "___ln_En" if "___ln_En" in vn else None
    ok = nc.mark_pending_review_in_notion(pid, video_name=vn, lang_suffix=lang)
    status = "OK" if ok else "FAIL"
    print(f"  {vn}: {status}")
print("Done")
