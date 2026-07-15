"""
app.py -- Flask server for the BabyBillion Pipeline Web Dashboard.
"""
from __future__ import annotations

import logging
from flask import Flask, jsonify, request, send_from_directory, render_template
from datetime import datetime, date

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
    failed = []
    
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
                    if not row:
                        # Fallback: use batcher sanitization (strips ___pg_ and ___ln_ tags)
                        try:
                            from batcher import _sanitize_video_name
                            sanitized = _sanitize_video_name(stem)
                            row = csv_rows.get(sanitized)
                            if not row:
                                # Determine language from video_name suffix (___ln_Hi or ___ln_En)
                                vname = v.get("video_name", "")
                                if "___ln_Hi" in vname:
                                    row = csv_rows.get(f"{sanitized}_Hi")
                                elif "___ln_En" in vname:
                                    row = csv_rows.get(f"{sanitized}_En")
                                else:
                                    # Try both as last resort
                                    row = csv_rows.get(f"{sanitized}_Hi") or csv_rows.get(f"{sanitized}_En")
                        except ImportError:
                            pass
                    if not row and len(csv_rows) == 1:
                        # Last resort: if CSV has only 1 row, just use it
                        row = next(iter(csv_rows.values()))
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

        # Group by status — failed batches go to a separate group
        if b.get("upload_failed"):
            failed.append(b)
        elif b["status"] == "pending_first_review":
            pending.append(b)
        elif b["status"] == "pending_second_review":
            uploaded.append(b)
        else:
            finalized.append(b)
            
    # Sort by created_at descending
    pending.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    uploaded.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    finalized.sort(key=lambda x: x.get("finalized_date", "") or x.get("created_at", ""), reverse=True)
    failed.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    # Summary counts
    total_videos = sum(len(b.get("videos", [])) for b in pending + uploaded + finalized + failed)
    total_uploaded_videos = sum(len(b.get("videos", [])) for b in uploaded + finalized)
    total_failed_videos = sum(len(b.get("videos", [])) for b in failed)
    
    return jsonify({
        "pending": pending,
        "uploaded": uploaded,
        "finalized": finalized,
        "failed": failed,
        "summary": {
            "total_batches": len(pending) + len(uploaded) + len(finalized) + len(failed),
            "total_videos": total_videos,
            "pending_batches": len(pending),
            "uploaded_batches": len(uploaded),
            "finalized_batches": len(finalized),
            "failed_batches": len(failed),
            "total_uploaded_videos": total_uploaded_videos,
            "total_failed_videos": total_failed_videos,
        },
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

        # Strip ___pg_<hex> and ___ln_Hi/En pipeline tags for clean output name
        clean_name = _re.sub(r"___pg_[0-9a-f]+", "", stem)
        clean_name = _re.sub(r"___ln_(Hi|En|H|E)", "", clean_name)
        clean_name = _re.sub(r"_+", "_", clean_name).strip("_")

        csv_rows.append({
            "video_name": clean_name,
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

@app.route("/api/batches/<batch_name>/force-compress", methods=["POST"])
def force_compress_batch(batch_name):
    """Force-compress all MP4s in a batch folder using ffmpeg, ignoring size checks."""
    import threading

    batch_dir = os.path.join(uploader.BATCHES_DIR, batch_name)
    if not os.path.isdir(batch_dir):
        return jsonify({"error": f"Batch folder '{batch_name}' not found."}), 404

    mp4s = [f for f in os.listdir(batch_dir) if f.lower().endswith('.mp4')]
    if not mp4s:
        return jsonify({"error": f"No MP4 files found in {batch_name}."}), 400

    def _compress_thread():
        import compressor
        buf = batch_manager.global_log_buffer
        buf.write(f"\n[COMPRESS] Force-compressing {len(mp4s)} video(s) in {batch_name}...")
        total_before = 0
        total_after = 0
        for i, fname in enumerate(mp4s, 1):
            fpath = os.path.join(batch_dir, fname)
            before = os.path.getsize(fpath)
            total_before += before
            buf.write(f"  [{i}/{len(mp4s)}] {fname} ({before/(1024*1024):.1f} MB) — compressing...")

            # Force compress by calling _encode directly at CRF 28 (good quality + smaller)
            base, ext = os.path.splitext(fpath)
            tmp = f"{base}_fcomp{ext}"
            import subprocess
            crf_cmd = [
                "ffmpeg", "-y", "-i", fpath,
                "-vcodec", "libx264", "-crf", "28",
                "-vf", f"scale='min(1280,iw)':-2",
                "-acodec", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                tmp,
            ]
            try:
                result = subprocess.run(
                    crf_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=600,
                )
                if result.returncode == 0 and os.path.isfile(tmp):
                    after = os.path.getsize(tmp)
                    total_after += after
                    os.replace(tmp, fpath)
                    buf.write(f"    ✓ {before/(1024*1024):.1f} MB → {after/(1024*1024):.1f} MB")
                else:
                    total_after += before
                    buf.write(f"    ✗ ffmpeg failed — keeping original")
                    if os.path.isfile(tmp):
                        os.remove(tmp)
            except subprocess.TimeoutExpired:
                total_after += before
                buf.write(f"    ✗ ffmpeg timed out — keeping original")
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except Exception as e:
                total_after += before
                buf.write(f"    ✗ Error: {e}")
                if os.path.isfile(tmp):
                    os.remove(tmp)

        buf.write(f"\n[COMPRESS] Done! {total_before/(1024*1024):.1f} MB → {total_after/(1024*1024):.1f} MB total")

        # Update batch size in batches.json
        try:
            batches = batch_manager.load_batches()
            if batch_name in batches:
                new_size = sum(os.path.getsize(os.path.join(batch_dir, f))
                               for f in os.listdir(batch_dir) if f.lower().endswith('.mp4'))
                batches[batch_name]["total_size_mb"] = round(new_size / (1024 * 1024), 2)
                batch_manager.save_batches(batches)
        except Exception:
            pass

    t = threading.Thread(target=_compress_thread, daemon=True)
    t.start()
    return jsonify({"message": f"Force-compressing {len(mp4s)} video(s) in {batch_name}. Check logs."})

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

@app.route("/api/batches/<batch_name>/clear-local", methods=["POST"])
def clear_local_batch(batch_name):
    """Clear a batch from local storage and UI only — does NOT touch Notion."""
    import shutil
    import state_manager as sm

    errors = []

    # Stop upload if running for this batch
    if batch_manager.upload_running and batch_manager.upload_batch_name == batch_name:
        batch_manager.stop_automated_upload()
        import time
        time.sleep(1)

    # Reset state.json entries (clear batch assignment, keep everything else)
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

    # Delete files from disk
    batch_dir = os.path.join(uploader.BATCHES_DIR, batch_name)
    csv_path = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.csv")
    zip_path = os.path.join(uploader.BATCHES_DIR, f"{batch_name}.zip")
    import time
    for path, label in [(batch_dir, "folder"), (csv_path, "CSV"), (zip_path, "ZIP")]:
        for attempt in range(3):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                elif os.path.isfile(path):
                    os.remove(path)
                break
            except PermissionError:
                if attempt < 2:
                    time.sleep(1)
                else:
                    errors.append(f"{label}: file locked")
            except Exception as e:
                errors.append(f"{label}: {e}")
                break

    if errors:
        return jsonify({"message": f"Cleared locally with warnings: {'; '.join(errors)}"})

    log.info(f"Batch {batch_name} cleared from local storage (Notion untouched)")
    return jsonify({"message": f"'{batch_name}' cleared from local storage. Notion untouched."})

@app.route("/api/batches/clear-all-local", methods=["POST"])
def clear_all_local_batches():
    """Clear only PENDING batches from local storage — preserves Uploaded/Finalized."""
    import shutil
    import state_manager as sm

    batches = batch_manager.load_batches()

    # Identify which batches to clear (only pending, not uploaded/finalized)
    to_clear = []
    to_keep = {}
    for name, b in batches.items():
        status = b.get("status", "")
        if status in ("pending_second_review", "finalized"):
            to_keep[name] = b  # preserve uploaded & finalized
        elif b.get("upload_failed"):
            to_keep[name] = b  # preserve failed (for tracking)
        else:
            to_clear.append(name)

    # Reset state.json batch references only for cleared batches
    cleared = 0
    try:
        state = sm.get_all()
        for page_id, rec in state.items():
            if isinstance(rec, dict) and rec.get("batch") in to_clear:
                sm.upsert(page_id, pipeline_status="pending", batch="", local_file="")
                cleared += 1
    except Exception as e:
        log.error(f"Error clearing state refs: {e}")

    # Delete batch files from disk only for cleared batches
    deleted_files = 0
    if os.path.isdir(uploader.BATCHES_DIR):
        for batch_name in to_clear:
            for entry in [batch_name, f"{batch_name}.csv", f"{batch_name}.zip"]:
                full = os.path.join(uploader.BATCHES_DIR, entry)
                try:
                    if os.path.isdir(full):
                        shutil.rmtree(full)
                        deleted_files += 1
                    elif os.path.isfile(full):
                        os.remove(full)
                        deleted_files += 1
                except Exception as e:
                    log.warning(f"Could not delete {entry}: {e}")

    # Save batches.json with only the kept batches
    batch_manager.save_batches(to_keep)

    msg = (f"Cleared {len(to_clear)} pending batch(es). "
           f"{cleared} state refs reset, {deleted_files} files removed. "
           f"{len(to_keep)} uploaded/finalized/failed batch(es) preserved.")
    log.info(msg)
    return jsonify({"message": msg})

@app.route("/api/notion-days", methods=["GET"])
def get_notion_days():
    """Return available day groupings from the Notion 'Ready to Upload' view."""
    import notion_client
    try:
        days = notion_client.query_available_days()
        return jsonify({"days": days})
    except Exception as e:
        log.error(f"Error fetching Notion days: {e}")
        return jsonify({"error": str(e), "days": []}), 500

@app.route("/api/batches/run-pipeline", methods=["POST"])
def run_pipeline():
    data = request.json or {}
    batch_only = data.get("batch_only", False)
    max_batches = data.get("max_batches", None)
    day_filter = data.get("day_filter", None)  # list of YYYY-MM-DD strings
    success, msg = batch_manager.start_pipeline_batching(batch_only=batch_only, max_batches=max_batches, day_filter=day_filter)
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

@app.route("/api/batches/<batch_name>/retry", methods=["POST"])
def retry_batch(batch_name):
    """Clear the upload_failed flag and re-queue batch for upload."""
    batches = batch_manager.load_batches()
    if batch_name not in batches:
        return jsonify({"error": f"Batch '{batch_name}' not found."}), 400
    b = batches[batch_name]
    if not b.get("upload_failed"):
        return jsonify({"error": f"Batch '{batch_name}' is not in failed state."}), 400
    # Reset failure state
    b["upload_failed"] = False
    b["fail_reason"] = None
    b["status"] = "pending_first_review"
    b["upload_completed"] = False
    for v in b.get("videos", []):
        if v.get("pipeline_status") in ("upload_failed", "uploaded_approval_failed"):
            v["pipeline_status"] = "batched"
    batch_manager.save_batches(batches)
    log.info(f"Batch '{batch_name}' retry: cleared failure, moved back to pending.")
    return jsonify({"message": f"Batch '{batch_name}' moved back to Pending Review for retry."})

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

# ── BFB (Bottle-Fed Billionaires) API ─────────────────────────────────────────
import bfb_notion_client

@app.route("/api/bfb/teachers")
def bfb_teachers():
    """Return teacher names and their Ready To Upload video counts."""
    try:
        summaries = bfb_notion_client.query_bfb_teachers_summary()
        return jsonify({"ok": True, "teachers": summaries})
    except Exception as e:
        log.error(f"Error fetching BFB teacher summary: {e}")
        return jsonify({"ok": False, "error": str(e), "teachers": []}), 500

@app.route("/api/bfb/videos")
def bfb_videos():
    """Return videos in Ready To Upload for a specific teacher (or all)."""
    teacher = request.args.get("teacher")  # None = all teachers
    try:
        videos = bfb_notion_client.query_bfb_ready_to_upload(teacher=teacher)
        return jsonify({"ok": True, "videos": videos, "total": len(videos)})
    except Exception as e:
        log.error(f"Error fetching BFB videos: {e}")
        return jsonify({"ok": False, "error": str(e), "videos": []}), 500

@app.route("/api/bfb/download", methods=["POST"])
def bfb_download():
    """Download selected BFB videos and create batches (same pipeline as AI Sprint)."""
    data = request.json or {}
    teacher = data.get("teacher")  # optional filter
    video_ids = data.get("video_ids")  # optional list of page_ids to download (None = all)

    if batch_manager.pipeline_running:
        return jsonify({"error": "Pipeline is already running. Stop it first."}), 400

    import threading

    def _bfb_download_thread():
        batch_manager.pipeline_running = True
        buf = batch_manager.global_log_buffer
        buf.write("\n============================================================")
        buf.write(f"BFB DOWNLOAD: Starting for teacher={teacher or 'ALL'}")
        buf.write("============================================================\n")

        try:
            # 1. Fetch videos from BFB database
            all_videos = bfb_notion_client.query_bfb_ready_to_upload(teacher=teacher)
            if video_ids:
                all_videos = [v for v in all_videos if v["page_id"] in video_ids]

            buf.write(f"[BFB] Found {len(all_videos)} video(s) to download")

            if not all_videos:
                buf.write("[BFB] No videos to download.")
                return

            # 2. Download each video using the existing downloader
            import downloader
            import state_manager as sm

            downloaded = []
            for i, v in enumerate(all_videos, 1):
                vname = v["video_name"]
                link = v["drive_link"]
                buf.write(f"\n[BFB] [{i}/{len(all_videos)}] Downloading: {vname}")
                buf.write(f"  Link: {link[:80]}...")

                # Check if already downloaded
                state_key = v["page_id"] + v.get("lang_suffix", "")
                existing = sm.get(state_key)
                if existing and existing.get("pipeline_status") in ("downloaded", "batched", "uploaded"):
                    buf.write(f"  ⏭ Already processed (status={existing['pipeline_status']})")
                    continue

                try:
                    local_path = downloader.download_video(v["page_id"], vname, link)
                    if local_path and os.path.isfile(local_path):
                        size_mb = os.path.getsize(local_path) / (1024 * 1024)
                        buf.write(f"  ✓ Downloaded ({size_mb:.1f} MB)")
                        v["local_file"] = local_path
                        downloaded.append(v)

                        # Update state.json
                        sm.upsert(state_key,
                                  video_name=v["video_name"],
                                  page_id=v["page_id"],
                                  age_group=v.get("age_group", ""),
                                  category=v.get("category", ""),
                                  local_file=local_path,
                                  pipeline_status="downloaded",
                                  source_db="bfb")

                        # Mark as moved to upload in Notion
                        bfb_notion_client.mark_bfb_moved_to_upload(v["page_id"])
                    else:
                        buf.write(f"  ✗ Download failed or file missing")
                except Exception as e:
                    buf.write(f"  ✗ Error: {e}")

            buf.write(f"\n[BFB] Downloaded {len(downloaded)}/{len(all_videos)} videos")

            if downloaded:
                # 3. Create batches using existing batcher
                buf.write("\n[BFB] Creating batches from downloaded videos...")
                import batcher
                batch_names = batcher.run(downloaded)
                buf.write(f"[BFB] Created {len(batch_names)} batch(es): {batch_names}")

                # 4. Scan and register batches in the dashboard
                batch_manager.scan_and_register_batches()
                buf.write("[BFB] Batches registered in dashboard")

        except Exception as e:
            buf.write(f"[BFB] ERROR: {e}")
            log.error(f"BFB download error: {e}")
        finally:
            batch_manager.pipeline_running = False
            batch_manager.active_pipeline_process = None
            buf.write("\n[BFB] Download pipeline complete.")

    t = threading.Thread(target=_bfb_download_thread, daemon=True)
    t.start()
    return jsonify({"message": f"BFB download started for teacher={teacher or 'ALL'}. Monitor logs."})

@app.route("/bfb")
def bfb_page():
    return render_template("bfb.html")

@app.route("/api/bfb/pipeline-summary")
def bfb_pipeline_summary():
    """Cross-reference BFB Notion 'Ready To Upload' with state.json and batches.json
    to produce pipeline stage counts for the BFB page."""
    try:
        # 1. Count videos ready on Notion (not yet downloaded)
        teacher_summaries = bfb_notion_client.query_bfb_teachers_summary()
        notion_ready_total = sum(t["video_count"] for t in teacher_summaries)

        # 2. Count BFB videos in state.json that are downloaded but not batched
        import state_manager as sm
        state = sm.get_all()
        downloaded_not_batched = 0
        for key, entry in state.items():
            if entry.get("source_db") == "bfb" and entry.get("pipeline_status") == "downloaded":
                downloaded_not_batched += 1

        # 3. Count BFB batches by status from batches.json
        batches = batch_manager.load_batches()
        bb_batches = {k: v for k, v in batches.items() if k.startswith("Batch_BB")}

        batch_counts = {"not_registered": 0, "registered": 0, "uploaded": 0, "upload_failed": 0, "finalized": 0}
        batch_video_counts = {"not_registered": 0, "registered": 0, "uploaded": 0, "upload_failed": 0, "finalized": 0}

        for name, b in bb_batches.items():
            st = b.get("status", "")
            vids = b.get("video_count") or len(b.get("videos", []))
            if st in ("pending_first_review", "pending"):
                batch_counts["registered"] += 1
                batch_video_counts["registered"] += vids
            elif st == "pending_second_review":
                batch_counts["uploaded"] += 1
                batch_video_counts["uploaded"] += vids
            elif st == "finalized":
                batch_counts["finalized"] += 1
                batch_video_counts["finalized"] += vids
            elif st == "failed" or b.get("upload_failed"):
                batch_counts["upload_failed"] += 1
                batch_video_counts["upload_failed"] += vids
            else:
                # not_registered (no status or unknown)
                batch_counts["not_registered"] += 1
                batch_video_counts["not_registered"] += vids

        return jsonify({
            "ok": True,
            "notion_ready": notion_ready_total,
            "downloaded": downloaded_not_batched,
            "teachers": teacher_summaries,
            "batch_counts": batch_counts,
            "batch_video_counts": batch_video_counts,
        })
    except Exception as e:
        log.error(f"BFB pipeline summary error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/bfb/batches")
def bfb_batches():
    """Return all Batch_BB_* batches with normalized status."""
    batches = batch_manager.load_batches()
    result = []
    for name, b in sorted(batches.items()):
        if not name.startswith("Batch_BB"):
            continue
        st = b.get("status", "")
        # Normalize status for frontend
        if st in ("pending_first_review", "pending"):
            norm = "pending"
        elif st == "pending_second_review":
            norm = "uploaded"
        elif st == "finalized":
            norm = "finalized"
        elif st == "failed" or b.get("upload_failed"):
            norm = "failed"
        else:
            norm = "not_registered"

        zip_path = os.path.join(os.path.dirname(__file__), "batches", f"{name}.zip")
        zip_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 1) if os.path.isfile(zip_path) else 0

        result.append({
            "batch_name": name,
            "status": norm,
            "video_count": b.get("video_count") or len(b.get("videos", [])),
            "zip_size_mb": zip_mb,
            "job_id": b.get("upload_job_id"),
            "created_at": b.get("created_at"),
        })
    return jsonify({"ok": True, "batches": result})

# ── Upload History ────────────────────────────────────────────────────────────
import upload_history

@app.route("/api/upload-history")
def get_upload_history():
    """Get recent upload history records."""
    limit = request.args.get("limit", default=200, type=int)
    records = upload_history.get_history(limit=limit)
    stats = upload_history.get_stats()
    return jsonify({"records": records, "stats": stats})

@app.route("/api/upload-history/stats")
def get_upload_stats():
    """Get aggregate upload stats."""
    return jsonify(upload_history.get_stats())

@app.route("/api/submission-tracker")
def get_submission_tracker():
    """Track CMS job submissions: which succeeded, which failed, and what videos each contains."""
    return jsonify(upload_history.get_submission_tracker())

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

# ── YouTube Channel Manager ──────────────────────────────────────────────────
import yt_channel_manager as yt_mgr

@app.route("/channels")
def channels_page():
    return render_template("channels.html")

@app.route("/api/yt-channels")
def yt_channels_list():
    """List all tracked YouTube channels with their stats."""
    channels = yt_mgr.load_channels()
    result = []
    for ch in channels:
        stats = yt_mgr.get_channel_stats(ch)
        result.append({**ch, "stats": stats})
    return jsonify({"channels": result})

@app.route("/api/yt-channels/add", methods=["POST"])
def yt_channels_add():
    """Add a new YouTube channel to track."""
    data = request.json or {}
    required = ["id", "name", "url"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"'{field}' is required"}), 400

    channel_data = {
        "id": data["id"],
        "name": data["name"],
        "url": data["url"],
        "registry_file": f"{data['id']}_registry.csv",
        "download_dir": f"{data['id']}_downloads",
        "batch_dir": f"{data['id']}_batches",
        "batch_prefix": f"Batch_{data['id'][:4].upper()}",
        "csv_defaults": {
            "channel_name": data.get("channel_name", data["id"]),
            "categories_name": data.get("categories_name", "Entertainment"),
            "age_groups": data.get("age_groups", ""),
            "tags": "",
            "playlist_name": "",
            "content_formats": "",
            "content_types": data.get("content_types", "Original"),
            "language": data.get("language", "English"),
        }
    }
    try:
        yt_mgr.add_channel(channel_data)
        return jsonify({"ok": True, "channel": channel_data})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/yt-channels/<channel_id>/remove", methods=["POST"])
def yt_channels_remove(channel_id):
    ok = yt_mgr.remove_channel(channel_id)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "Channel not found"}), 404

@app.route("/api/yt-channels/<channel_id>/check", methods=["POST"])
def yt_channels_check(channel_id):
    """Check for new videos on a channel (hits YouTube)."""
    ch = yt_mgr.get_channel(channel_id)
    if not ch:
        return jsonify({"error": "Channel not found"}), 404
    try:
        result = yt_mgr.check_new_videos(ch)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/yt-channels/<channel_id>/download", methods=["POST"])
def yt_channels_download(channel_id):
    """Start downloading + batching new videos (background task)."""
    ch = yt_mgr.get_channel(channel_id)
    if not ch:
        return jsonify({"error": "Channel not found"}), 404

    task = yt_mgr.get_task_status(channel_id)
    if task and task["status"] == "running":
        return jsonify({"error": "Download already in progress"}), 400

    yt_mgr.download_and_batch(channel_id)
    return jsonify({"ok": True, "message": "Download started"})

@app.route("/api/yt-channels/<channel_id>/status")
def yt_channels_status(channel_id):
    """Get current download task status."""
    task = yt_mgr.get_task_status(channel_id)
    if not task:
        return jsonify({"status": "idle"})
    return jsonify(task)

@app.route("/api/yt-channels/<channel_id>/registry")
def yt_channels_registry(channel_id):
    """Get the full registry for a channel."""
    ch = yt_mgr.get_channel(channel_id)
    if not ch:
        return jsonify({"error": "Channel not found"}), 404
    registry = yt_mgr.load_registry(ch)
    videos = list(registry.values())
    videos.sort(key=lambda x: x.get("safe_name", ""))
    return jsonify({"videos": videos, "total": len(videos)})

@app.route("/api/yt-channels/global-summary")
def yt_channels_global_summary():
    """Get global batch summary (Pending/Uploaded/Failed/Finalized) across all sources."""
    batches = batch_manager.load_batches()
    pending = uploaded = failed = finalized = 0
    for name, b in batches.items():
        status = b.get("status", "")
        is_failed = b.get("upload_failed", False)
        if is_failed:
            failed += 1
        elif status == "pending_first_review":
            pending += 1
        elif status == "pending_second_review":
            uploaded += 1
        elif status == "finalized":
            finalized += 1
    return jsonify({
        "pending": pending,
        "uploaded": uploaded,
        "failed": failed,
        "finalized": finalized,
        "total": len(batches),
    })

@app.route("/api/yt-channels/<channel_id>/pipeline-summary")
def yt_channels_pipeline_summary(channel_id):
    """Get comprehensive pipeline summary for a channel — counts at every stage."""
    ch = yt_mgr.get_channel(channel_id)
    if not ch:
        return jsonify({"error": "Channel not found"}), 404
    summary = yt_mgr.get_pipeline_summary(ch)
    return jsonify(summary)

@app.route("/api/yt-channels/<channel_id>/videos")
def yt_channels_videos_by_status(channel_id):
    """Get videos filtered by registry status. ?status=pending|downloaded|failed|batched"""
    ch = yt_mgr.get_channel(channel_id)
    if not ch:
        return jsonify({"error": "Channel not found"}), 404
    status = request.args.get("status", "pending")
    videos = yt_mgr.get_videos_by_status(ch, status)
    return jsonify({"videos": videos, "count": len(videos)})

@app.route("/api/yt-channels/<channel_id>/batches")
def yt_channels_batches(channel_id):
    """Get batch list with upload status for a channel."""
    ch = yt_mgr.get_channel(channel_id)
    if not ch:
        return jsonify({"error": "Channel not found"}), 404
    batches = yt_mgr.get_channel_batches(ch)
    return jsonify({"batches": batches})

@app.route("/api/yt-channels/<channel_id>/register-batches", methods=["POST"])
def yt_channels_register(channel_id):
    """Register channel batches into main dashboard for upload."""
    ch = yt_mgr.get_channel(channel_id)
    if not ch:
        return jsonify({"error": "Channel not found"}), 404
    data = request.json or {}
    batch_names = data.get("batch_names")  # None = all unregistered
    result = yt_mgr.register_batches_for_upload(ch, batch_names)
    # Rescan in batch_manager
    try:
        batch_manager.scan_and_register_batches()
    except Exception:
        pass
    return jsonify({"ok": True, **result})

@app.route("/api/yt-channels/<channel_id>/upload-all", methods=["POST"])
def yt_channels_upload_all(channel_id):
    """Register all unregistered batches then trigger upload-all-submit."""
    ch = yt_mgr.get_channel(channel_id)
    if not ch:
        return jsonify({"error": "Channel not found"}), 404

    # First register any unregistered batches
    reg_result = yt_mgr.register_batches_for_upload(ch)
    try:
        batch_manager.scan_and_register_batches()
    except Exception:
        pass

    # Start upload-all
    success, msg = batch_manager.start_upload_all_submit()
    return jsonify({
        "ok": success,
        "message": msg,
        "registered": reg_result.get("registered", 0),
        "skipped": reg_result.get("skipped", 0),
    })

@app.route("/api/yt-channels/upload-status")
def yt_channels_upload_status():
    """Get current upload pipeline status."""
    return jsonify({
        "upload_running": batch_manager.upload_running,
        "upload_paused": batch_manager.upload_paused,
        "upload_batch_name": batch_manager.upload_batch_name,
        "pipeline_running": batch_manager.pipeline_running,
    })

@app.route("/api/yt-channels/stop-upload", methods=["POST"])
def yt_channels_stop_upload():
    """Stop the upload pipeline."""
    success, msg = batch_manager.stop_automated_upload()
    if not success:
        # Try harder
        import subprocess as sp
        for proc in ("chromedriver", "chrome"):
            try:
                sp.run(["taskkill", "/F", "/IM", f"{proc}.exe", "/T"],
                       capture_output=True, timeout=5)
            except Exception:
                pass
        batch_manager.upload_running = False
        batch_manager.upload_batch_name = None
        batch_manager.upload_paused = False
        msg = "Upload stopped (forced)"
    return jsonify({"ok": True, "message": msg})

@app.route("/api/yt-channels/batch/<batch_name>/upload", methods=["POST"])
def yt_channels_single_upload(batch_name):
    """Upload a single batch via Selenium."""
    success, msg = batch_manager.start_automated_upload(batch_name)
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"ok": True, "message": msg})

@app.route("/api/yt-channels/batch/<batch_name>/retry", methods=["POST"])
def yt_channels_batch_retry(batch_name):
    """Retry a failed batch."""
    batches = batch_manager.load_batches()
    if batch_name not in batches:
        return jsonify({"error": f"Batch '{batch_name}' not found."}), 404
    b = batches[batch_name]
    b["upload_failed"] = False
    b["fail_reason"] = None
    b["status"] = "pending_first_review"
    b["upload_completed"] = False
    for v in b.get("videos", []):
        if v.get("pipeline_status") in ("upload_failed", "uploaded_approval_failed"):
            v["pipeline_status"] = "batched"
    batch_manager.save_batches(batches)
    return jsonify({"ok": True, "message": f"Batch '{batch_name}' reset for retry."})

@app.route("/api/yt-channels/batch/<batch_name>/finalize", methods=["POST"])
def yt_channels_batch_finalize(batch_name):
    """Finalize a batch (mark complete, cleanup)."""
    batches = batch_manager.load_batches()
    if batch_name not in batches:
        return jsonify({"error": f"Batch '{batch_name}' not found."}), 404
    b = batches[batch_name]
    b["status"] = "finalized"
    b["finalized_date"] = datetime.now().isoformat()
    for v in b.get("videos", []):
        v["pipeline_status"] = "finalized"
    batch_manager.save_batches(batches)
    return jsonify({"ok": True, "message": f"Batch '{batch_name}' finalized."})

@app.route("/api/yt-channels/batch/<batch_name>/mark-uploaded", methods=["POST"])
def yt_channels_batch_mark_uploaded(batch_name):
    """Mark a batch as uploaded."""
    data = request.json or {}
    job_id = data.get("job_id") or "MANUAL"
    success, msg = batch_manager.mark_batch_uploaded(batch_name, job_id)
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"ok": True, "message": msg})

@app.route("/api/yt-channels/batch/<batch_name>/set-status", methods=["POST"])
def yt_channels_batch_set_status(batch_name):
    """Manual override: set a batch to any status.
    Body: { "status": "pending_first_review"|"pending_second_review"|"finalized"|"failed"|"not_registered" }
    """
    data = request.json or {}
    new_status = data.get("status")
    valid = {"pending_first_review", "pending_second_review", "finalized", "failed", "not_registered"}
    if new_status not in valid:
        return jsonify({"error": f"Invalid status. Use one of: {', '.join(sorted(valid))}"}), 400

    batches = batch_manager.load_batches()

    if new_status == "not_registered":
        # Remove from batches.json entirely (unregister)
        if batch_name in batches:
            del batches[batch_name]
            batch_manager.save_batches(batches)
        return jsonify({"ok": True, "message": f"'{batch_name}' unregistered."})

    if batch_name not in batches:
        return jsonify({"error": f"Batch '{batch_name}' not found in batches.json. Register it first."}), 404

    b = batches[batch_name]
    b["status"] = new_status
    if new_status == "failed":
        b["upload_failed"] = True
        b["fail_reason"] = data.get("reason", "Manual override")
    else:
        b["upload_failed"] = False
        b["fail_reason"] = None
    if new_status == "finalized":
        b["finalized_date"] = datetime.now().isoformat()
    batch_manager.save_batches(batches)

    display = {"pending_first_review":"registered","pending_second_review":"uploaded","finalized":"finalized","failed":"failed"}.get(new_status, new_status)
    return jsonify({"ok": True, "message": f"'{batch_name}' → {display}"})

if __name__ == "__main__":
    # Kill any zombie servers still on port 5050 from previous runs
    import subprocess, re as _re, platform
    try:
        my_pid = os.getpid()
        if platform.system() == "Windows":
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if ":5050" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    if pid != my_pid:
                        try:
                            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=5)
                            print(f"  Killed zombie server on port 5050 (PID {pid})")
                        except Exception:
                            pass
        else:
            # macOS / Linux
            result = subprocess.run(
                ["lsof", "-ti", ":5050"], capture_output=True, text=True, timeout=5
            )
            for pid_str in result.stdout.strip().splitlines():
                pid = int(pid_str.strip())
                if pid != my_pid:
                    try:
                        os.kill(pid, 9)
                        print(f"  Killed zombie server on port 5050 (PID {pid})")
                    except Exception:
                        pass
    except Exception:
        pass

    # Start flask app locally
    app.run(host="127.0.0.1", port=5050, debug=False)
