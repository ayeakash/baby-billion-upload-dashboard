import csv

CSV = r"d:\BabyBillion\upload_dashboard\download_system\English_Hindi Videos Marking - All Videos.csv"
with open(CSV, "r", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

# Videos from our target playlists
target_pids = {
    "4e8e2dbf-bad4-4a56-8365-251a1cfc4a10": "Learn New Words",
    "b79bd45b-2c9c-4b7d-91a0-07c93a4dbea1": "Sounds & Words",
    "0eba9676-9d93-484f-8938-41e3ab588a7f": "Speak With Confidence",
    "4ee8120f-815e-4bc8-bbb1-d8fa87cb88b9": "ABC Learning",
}

for pid, pname in target_pids.items():
    print(f"\n=== {pname} ({pid[:12]}...) ===")
    count = 0
    for r in rows:
        if r.get("playlist_id", "").strip().lower() == pid.lower():
            lang = r.get("Language", "").strip()
            title = r.get("title", "")
            print(f"  [{lang:8s}] {title}")
            count += 1
    print(f"  Total: {count}")
