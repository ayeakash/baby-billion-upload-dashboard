"""Cross-reference ALL batches.json with CMS results and fix statuses."""
import json, os

b = json.load(open("batches.json", "r", encoding="utf-8"))

# COMPLETED on CMS (from ALL screenshot pages) - these are truly done
cms_completed = {
    # Old uploads (page 3-4)
    "1a05f317", "f7eb5ff9", "30f86cd9", "9df9eaa5", "92609673",
    "21793618", "b655a33e", "9b7317d9", "b2972d2c",
    # Second run (page 2-3)  
    "8e93cb43",  # 6 total - Batch_1011
    "f7eebfa8",  # 4 total - Batch_1013
    "4b469938",  # 2 total - Batch_1021
    "fd14d54c",  # 4 total - Batch_1022
    "9492b745",  # 1 total - Batch_1024
    "d9ba209f",  # 3 total - Batch_1025
    "f88782c3",  # 2 total - Batch_1026
    "5aef5b40",  # 4 total - Batch_1028
    # Third run (page 1)
    "a2db8c44",  # 2 total - Batch_1041
    "62a26f69",  # 2 total - Batch_1042
    "6a51511b",  # 1 total - Batch_1045/1046
    "1c0d68a1",  # 1 total - Batch_1038
}

# FAILED on CMS (from ALL screenshot pages) - need retry
cms_failed = {
    # Old failures
    "d04d7af8", "38e82f61", "c28fb891", "cb8ce178", "08996182",
    "d203b9f9", "46da1f8f",
    # Second run failures
    "3e28a751", "6268be96", "d6f6b6ac", "2788fccd", "9025840a",
    "0a96a58d", "ac71a69e", "8091d693",
    "e9c0493b", "eed3c7ec", "14276e22", "4b35c815",
    "ba11a984",  # Batch_1030 approval_failed
    # Third run failures  
    "9bc7fb33", "65997746", "498ac325", "903245e2",
    "4b116127", "4c19770b", "47cd4529",
    "a89c7ee1", "c4ae88f4", "ace86daa", "982d4c25",
}

# Also check which "submitted" entries actually map to approval_failed or 
# have job IDs matching failed CMS entries
# Some batches were re-tried and got new job IDs

reset_count = 0
keep_count = 0
for bn, d in sorted(b.items()):
    jid = (d.get("upload_job_id", "") or "")[:8]
    status = d.get("status", "")
    
    if status == "finalized":
        if jid in cms_completed:
            keep_count += 1
            # Truly completed, keep as-is
        elif jid in cms_failed:
            # Wrongly finalized - reset
            d["status"] = "pending_first_review"
            d["upload_failed"] = False
            d["upload_job_id"] = ""
            d.pop("fail_reason", None)
            d.pop("finalized_date", None)
            reset_count += 1
            print(f"RESET finalized: {bn} (CMS {jid}... was FAILED)")
        else:
            # Unknown job ID - could be new, check if it has files
            csv_ok = os.path.isfile(f"batches/{bn}.csv")
            zip_ok = os.path.isfile(f"batches/{bn}.zip")
            if csv_ok and zip_ok:
                # Has files but unknown CMS status - reset for safety
                d["status"] = "pending_first_review"
                d["upload_failed"] = False
                d["upload_job_id"] = ""
                d.pop("fail_reason", None)
                d.pop("finalized_date", None)
                reset_count += 1
                print(f"RESET unknown: {bn} (CMS {jid}... not in completed list)")
            else:
                keep_count += 1
    
    elif status == "pending_first_review" and d.get("upload_failed"):
        # Clear failed flag so Upload All picks it up
        csv_ok = os.path.isfile(f"batches/{bn}.csv")
        zip_ok = os.path.isfile(f"batches/{bn}.zip")
        if csv_ok and zip_ok:
            d["upload_failed"] = False
            d["upload_job_id"] = ""
            d.pop("fail_reason", None)
            reset_count += 1
            print(f"CLEARED failed: {bn} -> ready for retry")

json.dump(b, open("batches.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)

pending = sum(1 for x in b.values() if x.get("status") == "pending_first_review" and not x.get("upload_failed"))
finalized = sum(1 for x in b.values() if x.get("status") == "finalized")
failed = sum(1 for x in b.values() if x.get("upload_failed"))
print(f"\nDone! {reset_count} reset, {keep_count} kept as finalized")
print(f"Dashboard: {pending} Pending (will upload) | {finalized} Finalized | {failed} Failed")
