import json, os

b = json.load(open("batches.json", "r", encoding="utf-8"))

print("PENDING (will upload on Upload All):")
ready = 0
not_ready = 0
for bn, d in sorted(b.items()):
    if d.get("status") == "pending_first_review" and not d.get("upload_failed"):
        csv_ok = os.path.isfile(f"batches/{bn}.csv")
        zip_ok = os.path.isfile(f"batches/{bn}.zip")
        vids = len(d.get("videos", []))
        if csv_ok and zip_ok:
            ready += 1
            print(f"  READY  {bn}: {vids} videos")
        else:
            not_ready += 1
            print(f"  MISS   {bn}: csv={csv_ok} zip={zip_ok}")

print(f"\n  {ready} ready, {not_ready} missing files")

print("\nFINALIZED (already done):")
for bn, d in sorted(b.items()):
    if d.get("status") == "finalized":
        jid = d.get("upload_job_id", "")[:20]
        print(f"  {bn}: {jid}")

print(f"\nTotal: {len(b)} batches")
