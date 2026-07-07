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

# Disable browser caching so HTML/JS changes are always picked up
@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

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
                    if not row:
                        # Fallback: strip ___ln_Hi/___ln_En suffix (old CSVs without suffix)
                        stripped = _re.sub(r"___ln_(Hi|En|H|E)$", "", stem)
                        if stripped != stem:
                            row = csv_rows.get(stripped)
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
    import re as _re
    from category_mapper import get_category_fields, _normalize_age
    from config import ADMIN_CSV_HEADER, ADMIN_CHANNEL_NAME, ADMIN_CONTENT_TYPE

    csv_path = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.csv")
    batch_dir = os.path.join(uploader.BATCHES_DIR, batch_name)

    if not os.path.isdir(batch_dir):
        return jsonify({"error": f"Batch folder '{batch_name}' not found"}), 404

    # ── Build multiple lookup indexes for matching MP4 filenames → metadata ────
    #    We need robust matching because filenames may differ from video_name
    #    (e.g. parentheses/commas stripped, ___pg_ tags present or absent).

    def _norm(n):
        """Normalize name for matching: spaces→_, remove commas/parens, collapse underscores."""
        n = n.replace(" ", "_").replace(",", "").replace("(", "").replace(")", "")
        n = _re.sub(r"_+", "_", n)
        return n.strip("_").lower()

    def _extract_page_id_from_filename(stem):
        """Extract page_id from ___pg_<hex> tag in filename, return with hyphens."""
        m = _re.search(r"___pg_([0-9a-f]{32})", stem)
        if m:
            h = m.group(1)
            return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
        return None

    # Primary source: batches.json (always has age_group and category)
    batches = batch_manager.load_batches()
    batch_record = batches.get(batch_name, {})
    batch_videos = batch_record.get("videos", [])

    # Index batches.json videos by: video_name, normalized name, page_id, local_file basename
    meta_by_name = {}       # video_name (exact & normalized) → video dict
    meta_by_page_id = {}    # page_id → video dict
    meta_by_local = {}      # local_file basename (no ext) → video dict
    for bv in batch_videos:
        vname = bv.get("video_name", "")
        pid   = bv.get("page_id", "")
        lf    = bv.get("local_file", "")
        if vname:
            meta_by_name[vname] = bv
            meta_by_name[_norm(vname)] = bv
        if pid:
            meta_by_page_id[pid] = bv
        if lf:
            meta_by_local[os.path.splitext(os.path.basename(lf))[0].lower()] = bv

    # Fallback source: state.json
    import state_manager as sm
    state = sm.get_all()
    state_by_name = {}
    state_by_page_id = {}
    state_by_local = {}
    for pid, rec in state.items():
        if not isinstance(rec, dict):
            continue
        vname = rec.get("video_name", "")
        lf    = rec.get("local_file", "")
        if vname:
            state_by_name[vname] = rec
            state_by_name[_norm(vname)] = rec
        if pid:
            state_by_page_id[pid] = rec
        if lf:
            state_by_local[os.path.splitext(os.path.basename(lf))[0].lower()] = rec

    # ── List mp4 files in the batch folder ────────────────────────────────────
    mp4_files = [f for f in os.listdir(batch_dir) if f.endswith(".mp4")]
    if not mp4_files:
        return jsonify({"error": "No .mp4 files found in batch folder"}), 400

    csv_rows = []
    unmatched = []
    for mp4 in mp4_files:
        stem = os.path.splitext(mp4)[0]
        norm_stem = _norm(stem)

        # ── Waterfall matching: try multiple strategies ───────────────────────
        rec = None
        extracted_pid = _extract_page_id_from_filename(stem)

        # 1. Exact or normalized name match in batches.json
        rec = meta_by_name.get(stem) or meta_by_name.get(norm_stem)

        # 2. Extract page_id from ___pg_ tag in filename → batches.json
        if not rec and extracted_pid:
            rec = meta_by_page_id.get(extracted_pid)

        # 3. Match by local_file basename → batches.json
        if not rec:
            rec = meta_by_local.get(stem.lower())

        # 4. Fallback to state.json with same strategies
        if not rec:
            rec = state_by_name.get(stem) or state_by_name.get(norm_stem)
        if not rec and extracted_pid:
            rec = state_by_page_id.get(extracted_pid)
        if not rec:
            rec = state_by_local.get(stem.lower())

        if not rec:
            rec = {}
            unmatched.append(stem)

        age_raw    = rec.get("age_group", "")
        age        = _normalize_age(age_raw) if age_raw else ""
        notion_cat = rec.get("category", "")

        if not age or not notion_cat:
            log.warning(f"  [REGEN] No metadata for {stem} — age={repr(age_raw)}, cat={repr(notion_cat)}")

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

        # Derive language from ___ln_ suffix in filename
        if "___ln_Hi" in stem or "___ln_H" in stem:
            language = "Hindi"
        elif "___ln_En" in stem or "___ln_E" in stem:
            language = "English"
        else:
            language = ""


        csv_rows.append({
            "video_name": stem,
            "categories_name": exact_cat,
            "age_groups": age,
            "channel_name": ADMIN_CHANNEL_NAME,
            "tags": "",
            "playlist_name": parent_cat,
            "content_formats": "",
            "content_types": ADMIN_CONTENT_TYPE,
            "language": language,
        })

    if unmatched:
        log.warning(f"  [REGEN] {len(unmatched)} file(s) had no metadata match: {unmatched[:5]}")

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
    """Delete a batch: stop upload if running, remove files, reset state."""
    import shutil
    import state_manager as sm

    # If this batch is currently uploading, stop it first
    if batch_manager.upload_running and batch_manager.upload_batch_name == batch_name:
        log.info(f"Stopping upload for {batch_name} before deleting...")
        batch_manager.stop_automated_upload()
        import time
        time.sleep(2)  # Give Chrome time to die

    batch_dir = os.path.join(uploader.BATCHES_DIR, batch_name)
    csv_path = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.csv")
    zip_path = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.zip")

    errors = []

    # Reset video states back to "pending" and clear Notion Upload Progress
    try:
        import notion_client
        batches_data = batch_manager.load_batches()
        batch_record = batches_data.get(batch_name, {})

        # Clear Upload Progress in Notion for each video in this batch
        for v in batch_record.get("videos", []):
            pid = v.get("page_id")
            if pid:
                try:
                    notion_client.clear_upload_progress_in_notion(pid)
                    batch_manager.global_log_buffer.write(
                        f"[NOTION] Cleared upload progress for: {v.get('video_name', pid)}"
                    )
                except Exception as ne:
                    batch_manager.global_log_buffer.write(
                        f"[WARNING] Failed to clear Notion progress for {v.get('video_name', pid)}: {ne}"
                    )

        # Reset state.json entries
        state = sm.get_all()
        for page_id, rec in state.items():
            if isinstance(rec, dict) and rec.get("batch") == batch_name:
                sm.upsert(page_id, pipeline_status="pending", batch="", local_file="")
    except Exception as e:
        errors.append(f"state/Notion reset: {e}")

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

@app.route("/api/batches/delete-all", methods=["POST"])
def delete_all_batches():
    """Delete ALL batches (pending, uploaded, finalized) at once.
    Also clears ALL batch references from state.json to prevent resurrection."""
    import shutil
    import state_manager as sm

    # 1. Clear Notion Upload Progress for ALL batched videos, then reset state.json
    try:
        import notion_client
        batches_data = batch_manager.load_batches()

        # Clear Upload Progress in Notion for every video across all batches
        for bname, brec in batches_data.items():
            for v in brec.get("videos", []):
                pid = v.get("page_id")
                if pid:
                    try:
                        notion_client.clear_upload_progress_in_notion(pid)
                    except Exception:
                        pass

        state = sm.get_all()
        cleared = 0
        for page_id, rec in state.items():
            if isinstance(rec, dict) and rec.get("batch"):
                sm.upsert(page_id, pipeline_status="pending", batch="", local_file="")
                cleared += 1
        log.info(f"Cleared batch references from {cleared} state.json records + Notion progress")
    except Exception as e:
        log.error(f"Error clearing state.json batch refs / Notion: {e}")

    # 2. Delete all batch files from disk
    deleted_files = 0
    if os.path.isdir(uploader.BATCHES_DIR):
        for entry in os.listdir(uploader.BATCHES_DIR):
            full = os.path.join(uploader.BATCHES_DIR, entry)
            try:
                if os.path.isdir(full) and entry.startswith("Batch_"):
                    shutil.rmtree(full)
                    deleted_files += 1
                elif os.path.isfile(full) and entry.startswith("Batch_"):
                    os.remove(full)
                    deleted_files += 1
            except Exception as e:
                log.warning(f"Could not delete {entry}: {e}")

    # 3. Clear batches.json completely
    batch_manager.save_batches({})

    msg = f"Deleted all batches. Cleared {cleared} state refs, removed {deleted_files} files."
    log.info(msg)
    return jsonify({"message": msg})

@app.route("/api/batches/run-pipeline", methods=["POST"])
def run_pipeline():
    data = request.json or {}
    batch_only = data.get("batch_only", False)
    max_batches = data.get("max_batches", None)
    success, msg = batch_manager.start_pipeline_batching(batch_only=batch_only, max_batches=max_batches)
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/batches/stop-pipeline", methods=["POST"])
def stop_pipeline():
    success, msg = batch_manager.stop_pipeline_batching()
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/kill-all-python", methods=["POST"])
def kill_all_python():
    """Kill all other Python processes on this machine, then restart self."""
    import subprocess as sp
    my_pid = os.getpid()
    try:
        # Get list of all python PIDs
        result = sp.run(
            ["powershell", "-Command",
             f"Get-Process python* -ErrorAction SilentlyContinue | Where-Object {{ $_.Id -ne {my_pid} }} | Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=5
        )
        pids = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
        killed = 0
        for pid in pids:
            try:
                sp.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=5)
                killed += 1
            except Exception:
                pass
        # Reset internal pipeline state
        batch_manager.pipeline_running = False
        batch_manager.active_pipeline_process = None
        batch_manager.pipeline_paused = False
        # Reset internal upload state
        batch_manager.upload_running = False
        batch_manager.upload_batch_name = None
        batch_manager.upload_paused = False
        # Also kill Chrome/chromedriver
        for proc in ("chromedriver", "chrome"):
            try:
                sp.run(["taskkill", "/F", "/IM", f"{proc}.exe", "/T"], capture_output=True, timeout=5)
            except Exception:
                pass
        batch_manager.global_log_buffer.write(f"\n[SYSTEM] Killed {killed} Python process(es) + Chrome. Dashboard still running (PID {my_pid}).")
        return jsonify({"message": f"Killed {killed} Python process(es) + Chrome. Dashboard still running."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/batches/stop-upload", methods=["POST"])
def stop_upload():
    success, msg = batch_manager.stop_automated_upload()
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/stop-everything", methods=["POST"])
def stop_everything():
    """Nuclear stop: kill pipeline, upload, Chrome, reset all state."""
    import subprocess as sp
    msgs = []

    # 1. Stop pipeline
    if batch_manager.pipeline_running:
        try:
            batch_manager.stop_pipeline_batching()
            msgs.append("Pipeline stopped")
        except Exception as e:
            msgs.append(f"Pipeline stop error: {e}")

    # 2. Stop upload
    if batch_manager.upload_running:
        try:
            batch_manager.stop_automated_upload()
            msgs.append("Upload stopped")
        except Exception as e:
            msgs.append(f"Upload stop error: {e}")

    # 3. Force-kill Chrome/chromedriver
    for proc in ("chromedriver", "chrome"):
        try:
            sp.run(["taskkill", "/F", "/IM", f"{proc}.exe", "/T"],
                   capture_output=True, timeout=5)
        except Exception:
            pass
    msgs.append("Chrome killed")

    # 4. Kill any other python processes (not us)
    my_pid = os.getpid()
    try:
        result = sp.run(
            ["powershell", "-Command",
             f"Get-Process python* -ErrorAction SilentlyContinue | Where-Object {{ $_.Id -ne {my_pid} }} | Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=5
        )
        pids = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
        for pid in pids:
            try:
                sp.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=5)
            except Exception:
                pass
        if pids:
            msgs.append(f"Killed {len(pids)} Python process(es)")
    except Exception:
        pass

    # 5. Reset all flags
    batch_manager.pipeline_running = False
    batch_manager.active_pipeline_process = None
    batch_manager.pipeline_paused = False
    batch_manager.upload_running = False
    batch_manager.upload_batch_name = None
    batch_manager.upload_paused = False

    summary = "; ".join(msgs) if msgs else "Nothing was running"
    batch_manager.global_log_buffer.write(f"\n[STOP] Everything stopped: {summary}")
    return jsonify({"message": f"All stopped. {summary}"})

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

@app.route("/api/batches/upload-all-submit", methods=["POST"])
def upload_all_submit():
    """Upload ALL pending batches + submit each for approval."""
    success, msg = batch_manager.start_upload_all_submit()
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
    """Return pages awaiting reviewer finalization, grouped by batch name from Notion."""
    try:
        reviews = batch_manager.get_pending_reviews()

        # Group reviews by batch_id stored in Notion (works across PCs)
        grouped = {}
        for r in reviews:
            bname = r.get("batch_id") or "Ungrouped"
            grouped.setdefault(bname, []).append(r)

        # Sort batches: Batch_NN naturally, Ungrouped last
        def batch_sort_key(name):
            if name == "Ungrouped":
                return (1, "")
            return (0, name)

        grouped_list = []
        for bname in sorted(grouped.keys(), key=batch_sort_key):
            grouped_list.append({
                "batch_name": bname,
                "reviews": grouped[bname],
            })

        return jsonify({"ok": True, "grouped": grouped_list, "total": len(reviews)})
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

@app.route("/api/pending-reviews/finalize-batch", methods=["POST"])
def finalize_batch_reviews():
    """Finalize all pending review pages for a specific batch."""
    data = request.json or {}
    page_ids = data.get("page_ids", [])
    if not page_ids:
        return jsonify({"ok": False, "message": "No page_ids provided."}), 400

    success = 0
    failed = 0
    for pid in page_ids:
        ok, msg = batch_manager.finalize_review(pid)
        if ok:
            success += 1
        else:
            failed += 1
            log.warning(f"Finalize failed for {pid}: {msg}")

    return jsonify({
        "ok": True,
        "success": success,
        "failed": failed,
        "message": f"Finalized {success}/{success + failed} pages."
    })

@app.route("/api/pending-reviews/<page_id>/reject", methods=["POST"])
def reject_one_review(page_id):
    """Reject/delete a pending review: clear Upload Progress so it can be re-downloaded."""
    try:
        import notion_client
        ok = notion_client.clear_upload_progress_in_notion(page_id)
        if ok:
            return jsonify({"ok": True, "message": f"Page {page_id} rejected — Upload Progress cleared."})
        else:
            return jsonify({"ok": False, "message": f"Failed to clear Upload Progress for {page_id}."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})

if __name__ == "__main__":
    # Kill any zombie servers still on port 5000 from previous runs
    import subprocess, re as _re
    try:
        my_pid = os.getpid()
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if ":5000" in line and "LISTENING" in line:
                parts = line.split()
                pid = int(parts[-1])
                if pid != my_pid:
                    try:
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=5)
                        print(f"  Killed zombie server on port 5000 (PID {pid})")
                    except Exception:
                        pass
    except Exception:
        pass

    # Start flask app locally
    app.run(host="127.0.0.1", port=5000, debug=False)
