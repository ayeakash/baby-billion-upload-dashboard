"""
app.py -- Flask server for the BabyBillion Pipeline Web Dashboard.
"""
from __future__ import annotations

import logging
from flask import Flask, jsonify, request, send_from_directory, render_template

# ── Add local pipeline/ to sys.path so we can import shared modules ──────────
import os
import sys
_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline")
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

# Set up logging for flask
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Import batch manager
import config
import batch_manager
import uploader

app = Flask(__name__, template_folder="templates")

# Initialize batches by scanning on startup
try:
    batch_manager.scan_and_register_batches()
except Exception as e:
    log.error(f"Failed to scan batches on startup: {e}")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/batches")
def get_batches():
    # Scan on request to pick up any changes from background runs
    try:
        batch_manager.scan_and_register_batches()
    except Exception as e:
        log.error(f"Error scanning batches: {e}")
        
    batches = batch_manager.load_batches()
    # Sort batches: pending reviews first, then uploaded, then finalized. Newest first within categories.
    sorted_batches = []
    
    # We want a lists of batches grouped by status for convenient UI consumption
    pending = []
    uploaded = []
    finalized = []
    
    for name, b in batches.items():
        # Check if the local directory still exists
        batch_dir = os.path.join(uploader.BATCHES_DIR, name)
        b["local_folder_exists"] = os.path.isdir(batch_dir)
        
        # Add zipped file size if zip exists
        zip_path = os.path.join(uploader.BATCHES_DIR, f"{name}.zip")
        if os.path.isfile(zip_path):
            size_mb = os.path.getsize(zip_path) / (1024 * 1024)
            b["zip_size_mb"] = round(size_mb, 2)
        else:
            b["zip_size_mb"] = 0

        # Enrich video records with CSV fields
        csv_path = os.path.join(uploader.BATCHES_DIR, f"{name}.csv")
        if os.path.isfile(csv_path):
            try:
                import csv as csv_mod
                with open(csv_path, "r", encoding="utf-8") as cf:
                    reader = csv_mod.DictReader(cf)
                    # Build lookup keyed by CSV video_name (the sanitized filename stem)
                    csv_rows = {}
                    for row in reader:
                        csv_vname = row.get("video_name", "").strip()
                        if csv_vname:
                            csv_rows[csv_vname] = row
                for v in b.get("videos", []):
                    # Try matching via local_file basename first (most reliable),
                    # then fall back to normalizing video_name
                    local_file = v.get("local_file", "")
                    if local_file:
                        stem = os.path.splitext(os.path.basename(local_file))[0]
                    else:
                        stem = v.get("video_name", "").replace(" ", "_")
                    row = csv_rows.get(stem)
                    if not row:
                        # Fallback: try video_name with spaces → underscores
                        row = csv_rows.get(v.get("video_name", "").replace(" ", "_"))
                    if not row:
                        # Fallback: try video_name as-is
                        row = csv_rows.get(v.get("video_name", ""))
                    if row:
                        # Sync video_name to the CSV version
                        v["video_name"] = row.get("video_name", v["video_name"])
                        v["categories_name"] = row.get("categories_name", "")
                        v["playlist_name"] = row.get("playlist_name", "")
                        v["channel_name"] = row.get("channel_name", "")
                        v["tags"] = row.get("tags", "")
                        v["content_formats"] = row.get("content_formats", "")
                        v["content_types"] = row.get("content_types", "")
                        v["age_group"] = row.get("age_groups", v.get("age_group", ""))
            except Exception as e:
                log.debug(f"Could not read CSV for {name}: {e}")

        # Group by status
        if b["status"] == "pending_first_review":
            pending.append(b)
        elif b["status"] == "pending_second_review":
            uploaded.append(b)
        else:
            finalized.append(b)
            
    # Sort by created_at descending
    pending.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    uploaded.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    finalized.sort(key=lambda x: x.get("finalized_date", "") or x.get("created_at", ""), reverse=True)
    
    return jsonify({
        "pending": pending,
        "uploaded": uploaded,
        "finalized": finalized,
        "pipeline_running": batch_manager.pipeline_running,
        "pipeline_paused": batch_manager.pipeline_paused,
        "upload_running": batch_manager.upload_running,
        "upload_paused": batch_manager.upload_paused,
        "upload_batch_name": batch_manager.upload_batch_name,
        "active_uploaded_batch": batch_manager.get_active_uploaded_batch(),
        "batch_size_mb": round(config.MAX_BATCH_BYTES / (1024 * 1024))
    })

@app.route("/api/batch-size", methods=["GET", "POST"])
def batch_size():
    if request.method == "GET":
        return jsonify({"batch_size_mb": round(config.MAX_BATCH_BYTES / (1024 * 1024))})
    data = request.json or {}
    mb = data.get("batch_size_mb")
    if mb is None or not isinstance(mb, (int, float)) or mb < 5 or mb > 500:
        return jsonify({"error": "batch_size_mb must be between 5 and 500"}), 400
    config.MAX_BATCH_BYTES = int(mb) * 1024 * 1024
    return jsonify({"message": f"Batch size set to {int(mb)} MB", "batch_size_mb": int(mb)})

@app.route("/api/csv-options")
def csv_options():
    """Serve all dropdown options from source-of-truth files."""
    import csv as csv_mod
    from category_mapper import MAPPING_CSV

    # Age groups
    age_groups = ["0-3", "3-6", "6+"]

    # Categories from mapping CSV, grouped by age
    categories_by_age = {}  # age -> [{parent, category}]
    parent_categories_by_age = {}  # age -> [parent names]
    if os.path.isfile(MAPPING_CSV):
        with open(MAPPING_CSV, "r", encoding="utf-8-sig") as f:
            reader = csv_mod.DictReader(f)
            for row in reader:
                age = row.get("Age", "").strip()
                parent = row.get("Parent Category", "").strip()
                cat = row.get("Playlist Name", "").strip()
                if not cat or cat.lower() == "playlist name":
                    continue
                categories_by_age.setdefault(age, []).append({
                    "parent": parent, "category": cat
                })
                if parent and parent not in parent_categories_by_age.get(age, []):
                    parent_categories_by_age.setdefault(age, []).append(parent)

    # Channel names, content types — add known values here
    channel_names = ["BabyBillion_Education", "learnup_tv", "cocomelon_nursery_rhymes"]
    content_types = ["Original", "Licensed"]
    content_formats = [""]
    tags = [""]

    return jsonify({
        "age_groups": age_groups,
        "categories_by_age": categories_by_age,
        "parent_categories_by_age": parent_categories_by_age,
        "channel_names": channel_names,
        "content_types": content_types,
        "content_formats": content_formats,
        "tags": tags
    })

@app.route("/api/batches/<batch_name>/update-csv", methods=["POST"])
def update_csv(batch_name):
    """Update a single field in a batch's CSV file."""
    import csv as csv_mod
    data = request.json or {}
    video_name = data.get("video_name")
    field = data.get("field")
    value = data.get("value", "")

    allowed_fields = {"video_name", "age_groups", "categories_name", "playlist_name",
                      "channel_name", "tags", "content_formats", "content_types"}
    if not video_name or not field:
        return jsonify({"error": "video_name and field are required"}), 400
    if field not in allowed_fields:
        return jsonify({"error": f"Field '{field}' is not editable"}), 400

    csv_path = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.csv")
    if not os.path.isfile(csv_path):
        return jsonify({"error": f"CSV not found for {batch_name}"}), 404

    try:
        # Read all rows
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv_mod.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)

        # Find and update the matching row
        found = False
        for row in rows:
            if row.get("video_name") == video_name:
                row[field] = value
                found = True
                break

        if not found:
            return jsonify({"error": f"Video '{video_name}' not found in CSV"}), 404

        # Write back
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        # If video_name changed, also rename the .mp4 file
        if field == "video_name" and value != video_name:
            batch_dir = os.path.join(uploader.BATCHES_DIR, batch_name)
            old_file = os.path.join(batch_dir, f"{video_name}.mp4")
            new_file = os.path.join(batch_dir, f"{value}.mp4")
            if os.path.isfile(old_file):
                try:
                    os.rename(old_file, new_file)
                    log.info(f"Renamed {old_file} -> {new_file}")
                except Exception as rename_err:
                    log.warning(f"CSV updated but file rename failed: {rename_err}")
                    return jsonify({"message": f"CSV updated but file rename failed: {rename_err}"})

        return jsonify({"message": f"Updated {field} for '{video_name}' in {batch_name}"})
    except Exception as e:
        log.error(f"Error updating CSV for {batch_name}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/batches/<batch_name>/regenerate-csv", methods=["POST"])
def regenerate_csv(batch_name):
    """Delete the CSV and regenerate it from the batch folder using category mapping."""
    import csv as csv_mod
    from category_mapper import get_category_fields
    from config import ADMIN_CSV_HEADER, ADMIN_CHANNEL_NAME, ADMIN_CONTENT_TYPE

    csv_path = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.csv")
    batch_dir = os.path.join(uploader.BATCHES_DIR, batch_name)

    if not os.path.isdir(batch_dir):
        return jsonify({"error": f"Batch folder '{batch_name}' not found"}), 404

    # Get video metadata from state.json for age_group and category
    import state_manager as sm
    state = sm.get_all()
    videos_in_batch = {
        v.get("video_name", os.path.splitext(os.path.basename(v.get("local_file", "")))[0]): v
        for v in state.values()
        if isinstance(v, dict) and v.get("batch") == batch_name
    }

    # List mp4 files in the batch folder
    mp4_files = [f for f in os.listdir(batch_dir) if f.endswith(".mp4")]
    if not mp4_files:
        return jsonify({"error": "No .mp4 files found in batch folder"}), 400

    csv_rows = []
    for mp4 in mp4_files:
        stem = os.path.splitext(mp4)[0]
        # Find matching state record
        rec = videos_in_batch.get(stem, {})
        age = rec.get("age_group", "")
        notion_cat = rec.get("category", "")

        # Resolve category mapping
        if "," in notion_cat:
            parts = [p.strip() for p in notion_cat.split(",") if p.strip()]
            parents, cats = [], []
            for p in parts:
                par, cat = get_category_fields(age, p)
                if par and par not in parents:
                    parents.append(par)
                cats.append(cat)
            parent_cat = ", ".join(parents)
            exact_cat = ", ".join(cats)
        else:
            parent_cat, exact_cat = get_category_fields(age, notion_cat)

        csv_rows.append({
            "video_name": stem,
            "categories_name": parent_cat,
            "age_groups": age,
            "channel_name": ADMIN_CHANNEL_NAME,
            "tags": "",
            "playlist_name": exact_cat,
            "content_formats": "",
            "content_types": ADMIN_CONTENT_TYPE,
        })

    # Delete old CSV and write new one
    try:
        if os.path.isfile(csv_path):
            os.remove(csv_path)
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=ADMIN_CSV_HEADER)
            writer.writeheader()
            writer.writerows(csv_rows)
        log.info(f"Regenerated CSV for {batch_name} with {len(csv_rows)} rows")
        return jsonify({"message": f"CSV regenerated for {batch_name} ({len(csv_rows)} videos)"})
    except Exception as e:
        log.error(f"Error regenerating CSV for {batch_name}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/batches/<batch_name>/delete", methods=["POST"])
def delete_batch(batch_name):
    """Delete a batch: remove folder, CSV, zip, batches.json entry, reset state to pending."""
    import shutil
    import state_manager as sm

    batch_dir = os.path.join(uploader.BATCHES_DIR, batch_name)
    csv_path = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.csv")
    zip_path = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.zip")

    errors = []

    # Reset video states back to "pending" (files are deleted with the batch)
    try:
        state = sm.get_all()
        for page_id, rec in state.items():
            if isinstance(rec, dict) and rec.get("batch") == batch_name:
                sm.upsert(page_id, pipeline_status="pending", batch="", local_file="")
    except Exception as e:
        errors.append(f"state reset: {e}")

    # Remove from batches.json
    try:
        batches = batch_manager.load_batches()
        if batch_name in batches:
            del batches[batch_name]
            batch_manager.save_batches(batches)
    except Exception as e:
        errors.append(f"batches.json: {e}")

    # Delete files (retry up to 3 times — subprocess may still hold handles briefly)
    import time
    for path, label in [(batch_dir, "folder"), (csv_path, "CSV"), (zip_path, "ZIP")]:
        for attempt in range(3):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                elif os.path.isfile(path):
                    os.remove(path)
                break  # success
            except PermissionError:
                if attempt < 2:
                    time.sleep(1)  # wait for subprocess to release handles
                else:
                    errors.append(f"{label}: file locked — try again in a few seconds")
            except Exception as e:
                errors.append(f"{label}: {e}")
                break

    if errors:
        log.warning(f"Batch {batch_name} deleted with errors: {errors}")
        return jsonify({"message": f"Batch deleted with warnings: {'; '.join(errors)}"})

    log.info(f"Batch {batch_name} fully deleted")
    return jsonify({"message": f"Batch '{batch_name}' deleted. Videos reset to 'pending' for re-download."})

@app.route("/api/batches/run-pipeline", methods=["POST"])
def run_pipeline():
    data = request.json or {}
    batch_only = data.get("batch_only", False)
    success, msg = batch_manager.start_pipeline_batching(batch_only=batch_only)
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/stop-pipeline", methods=["POST"])
def stop_pipeline():
    success, msg = batch_manager.stop_pipeline_batching()
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/stop-upload", methods=["POST"])
def stop_upload():
    success, msg = batch_manager.stop_automated_upload()
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/pause-pipeline", methods=["POST"])
def pause_pipeline():
    success, msg = batch_manager.pause_pipeline_batching()
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/resume-pipeline", methods=["POST"])
def resume_pipeline():
    success, msg = batch_manager.resume_pipeline_batching()
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/pause-upload", methods=["POST"])
def pause_upload():
    success, msg = batch_manager.pause_automated_upload()
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/resume-upload", methods=["POST"])
def resume_upload():
    success, msg = batch_manager.resume_automated_upload()
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/<batch_name>/upload", methods=["POST"])
def upload_batch(batch_name):
    success, msg = batch_manager.start_automated_upload(batch_name)
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/<batch_name>/mark-uploaded", methods=["POST"])
def mark_uploaded(batch_name):
    data = request.json or {}
    job_id = data.get("job_id") or "MANUAL"
    success, msg = batch_manager.mark_batch_uploaded(batch_name, job_id)
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/<batch_name>/mark-bad", methods=["POST"])
def mark_video_bad(batch_name):
    """Toggle a video's bad status within a batch."""
    data = request.json or {}
    page_id = data.get("page_id")
    bad = data.get("bad", True)
    reason = data.get("reason", "")
    if not page_id:
        return jsonify({"error": "page_id is required"}), 400
    success, msg = batch_manager.mark_video_bad(batch_name, page_id, bad, reason)
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/<batch_name>/finalize", methods=["POST"])
def finalize_batch(batch_name):
    success, msg = batch_manager.finalize_batch(batch_name)
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/<batch_name>/open-folder", methods=["POST"])
def open_folder(batch_name):
    batch_dir = os.path.abspath(os.path.join(uploader.BATCHES_DIR, batch_name))
    if not os.path.isdir(batch_dir):
        return jsonify({"error": f"Folder {batch_dir} does not exist."}), 404
    
    try:
        # Windows-specific folder open
        os.startfile(batch_dir)
        return jsonify({"message": f"Opened folder '{batch_name}' in Windows Explorer."})
    except Exception as e:
        log.error(f"Failed to open folder {batch_dir}: {e}")
        return jsonify({"error": f"Failed to open folder: {str(e)}"}), 500

@app.route("/api/logs")
def get_logs():
    index = request.args.get("index", default=0, type=int)
    lines, next_index = batch_manager.global_log_buffer.get_since(index)
    return jsonify({
        "lines": lines,
        "next_index": next_index,
        "pipeline_running": batch_manager.pipeline_running
    })

@app.route("/videos/<batch_name>/<filename>")
def play_video(batch_name, filename):
    directory = os.path.abspath(os.path.join(uploader.BATCHES_DIR, batch_name))
    if not os.path.isdir(directory):
        return "Batch folder not found", 404
    # Set headers correctly to allow video streaming (seeking)
    response = send_from_directory(directory, filename)
    response.headers["Accept-Ranges"] = "bytes"
    return response

# ── Cross-computer review routes ──────────────────────────────────────────────

@app.route("/api/pending-reviews")
def get_pending_reviews():
    """Return pages awaiting reviewer finalization (Status = 'Uploaded - Pending Review')."""
    try:
        reviews = batch_manager.get_pending_reviews()
        return jsonify({"ok": True, "reviews": reviews})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/pending-reviews/<page_id>/finalize", methods=["POST"])
def finalize_one_review(page_id):
    """Finalize a single page: check Upload box + set Upload Date."""
    ok, msg = batch_manager.finalize_review(page_id)
    return jsonify({"ok": ok, "message": msg})

@app.route("/api/pending-reviews/finalize-all", methods=["POST"])
def finalize_all_reviews():
    """Finalize all pending review pages at once."""
    success, failed, msg = batch_manager.finalize_all_reviews()
    return jsonify({"ok": True, "success": success, "failed": failed, "message": msg})

if __name__ == "__main__":
    # Start flask app locally
    app.run(host="127.0.0.1", port=5000, debug=False)

