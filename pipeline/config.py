"""
config.py — Pipeline settings (paths, mappings, timeouts).

  ╔══════════════════════════════════════════════════════════╗
  ║  DO NOT edit credentials here.                           ║
  ║  Put all your credentials in  credentials.py  instead.  ║
  ╚══════════════════════════════════════════════════════════╝

Priority order for secrets:
  1. credentials.py   (edit this file — it lives only on your machine)
  2. Environment variables  (fallback, useful for CI / scheduled tasks)
"""

import os

# ── Load credentials (credentials.py > env vars) ──────────────────────────────
try:
    import credentials as _creds
    _get = lambda key, default="": getattr(_creds, key, None) or os.environ.get(key, default)
except ImportError:
    _get = lambda key, default="": os.environ.get(key, default)

NOTION_TOKEN       = _get("NOTION_TOKEN")
NOTION_DATABASE_ID = _get("NOTION_DATABASE_ID")
BB_USERNAME        = _get("BB_USERNAME")
BB_PASSWORD        = _get("BB_PASSWORD")

# ── Notion column/property names (match exactly what's in your board) ──────────
PROP_VIDEO_NAME      = "Video Name"
PROP_AGE_GROUP       = "Age Group"
PROP_CATEGORY        = "Category"
PROP_STATUS          = "Status"
PROP_UPLOAD          = "Upload"
PROP_UPLOAD_DATE     = "Upload Date"
PROP_FINAL_VIDEO_HINDI_LINK   = "Final Video Hindi Link"
PROP_FINAL_VIDEO_ENGLISH_LINK = "Final Video English Link"
PROP_FAILED_UPLOAD   = "Failed to Upload"
PROP_REDO            = "Re-do"
PROP_REDO_REASON     = "reason for re-do"
PROP_HINDI_TITLE_ON_APP   = "Hindi Title on App"
PROP_ENGLISH_TITLE_ON_APP = "English Title on App"

# ── Status / upload values in Notion ──────────────────────────────────────────
STATUS_READY          = "Ready to Upload"
STATUS_UPLOADING      = "Uploading"          # claimed by a PC — other PCs skip it
STATUS_FAILED_UPLOAD  = "Failed to upload"
STATUS_PENDING_REVIEW = "Uploaded - Pending Review"
UPLOAD_NO      = "No"
UPLOAD_YES     = "Yes"

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))           # pipeline/
PROJECT_ROOT  = os.path.dirname(BASE_DIR)                            # upload_dashboard/
DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, "downloads")              # flat MP4 landing zone
BATCHES_DIR   = os.path.join(PROJECT_ROOT, "batches")                # Batch_01/, Batch_01.csv …
STATE_FILE    = os.path.join(PROJECT_ROOT, "state.json")
LOG_DIR       = os.path.join(PROJECT_ROOT, "logs")

# ── Batching ───────────────────────────────────────────────────────────────────
MAX_BATCH_BYTES = 30 * 1024 * 1024   # 30 MB - balanced for reliability + speed

# ── Admin site ────────────────────────────────────────────────────────────────
ADMIN_BASE_URL   = "https://cms-v1.d148rwrq639wa8.amplifyapp.com"
ADMIN_LOGIN_URL  = f"{ADMIN_BASE_URL}/login"
ADMIN_UPLOAD_URL = f"{ADMIN_BASE_URL}/dashboard/cms/content-upload"
# BB_USERNAME and BB_PASSWORD are loaded from credentials.py (see top of file)

UPLOAD_TYPE     = "Normal videos"  # radio button label on the upload page

# ── Admin CSV column mapping ───────────────────────────────────────────────────
ADMIN_CSV_HEADER   = ["video_name", "categories_name", "age_groups",
                      "channel_name", "tags", "playlist_name",
                      "content_formats", "content_types"]
ADMIN_CHANNEL_NAME = "BabyBillion_Education"
ADMIN_CONTENT_TYPE = "Original"

AGE_GROUP_MAP = {
    "under 3":        "0-3",
    "under 3 age":    "0-3",
    "0-3":            "0-3",
    "0-3 age group":  "0-3",
    "3-6":            "3-6",
    "3-6 age group":  "3-6",
    "6+":             "6+",
    "6+ age group":   "6+",
}

# ── Selenium ───────────────────────────────────────────────────────────────────
SELENIUM_WAIT_SEC     = 20
UPLOAD_RETRY_MAX      = 3
STATUS_POLL_SEC       = 10
STATUS_MAX_POLLS      = 30
