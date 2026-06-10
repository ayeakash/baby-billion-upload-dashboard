# BabyBillion Notion Pipeline — Setup Guide

## Files Created

```
D:\BabyBillion\YouTube Downloads\notion_pipeline\
├── pipeline.py          ← RUN THIS (main orchestrator)
├── config.py            ← All settings
├── notion_client.py     ← Notion API
├── downloader.py        ← Google Drive downloads
├── batcher.py           ← Batch grouper + CSV writer
├── zipper.py            ← ZIP creator
├── uploader.py          ← Selenium admin uploader
├── state_manager.py     ← state.json tracker
├── logs/                ← Auto-created on first run
├── downloads/           ← Auto-created — MP4 landing zone
└── batches/             ← Auto-created — Batch_01/, Batch_01.csv, .zip …
```

---

## One-Time Setup

### Step 1 — Install dependencies

```powershell
pip install gdown selenium webdriver-manager requests
```

### Step 2 — Create a Notion Integration

1. Go to **https://www.notion.so/my-integrations**
2. Click **"New integration"** → give it a name (e.g. `BabyBillion Pipeline`)
3. Copy the **"Internal Integration Token"** (starts with `secret_`)
4. Open your **AI Sprint Master Board** in Notion
5. Click **`···`** (top right) → **"Add connections"** → select your integration

### Step 3 — Get your Database ID

From the Notion URL:
```
https://www.notion.so/yourworkspace/34463e60e8f4805a85e0fff4388938c0?v=...
                                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                    This is your DATABASE_ID
```

### Step 4 — Set environment variables (PowerShell)

```powershell
$env:NOTION_TOKEN       = "secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
$env:NOTION_DATABASE_ID = "34463e60e8f4805a85e0fff4388938c0"
$env:BB_USERNAME        = "your_babybillion_admin_username"
$env:BB_PASSWORD        = "your_babybillion_admin_password"
```

> Alternatively, edit `config.py` directly to hardcode these values.

---

## Running the Pipeline

```powershell
cd "D:\BabyBillion\YouTube Downloads\notion_pipeline"
```

### Full run (recommended)
```powershell
python pipeline.py
```

### See what would be processed (no downloads/uploads)
```powershell
python pipeline.py --dry-run
```

### Check current pipeline state
```powershell
python pipeline.py --status
```

### Run headless (no browser window)
```powershell
python pipeline.py --headless
```

### Skip download (if videos already downloaded)
```powershell
python pipeline.py --skip-download
```

### Stop before uploading (download + batch + zip only)
```powershell
python pipeline.py --skip-upload
```

---

## How It Works (Each Run)

1. **Fetch** — Queries Notion for rows where `Status = "Ready to Upload"` AND `Upload = "No"`
2. **Download** — Downloads each video from Google Drive via `gdown`
3. **Batch** — Groups videos into sub-70MB folders with admin-format CSVs
4. **Zip** — Creates `.zip` archives per batch
5. **Upload** — Opens Chrome → logs into admin site → uploads each ZIP+CSV pair
6. **Track** — Updates `state.json` + sets `Upload = Yes` and `Upload Date = today` in Notion

### Re-running is safe
- Already-uploaded videos are skipped (tracked in `state.json`)
- Already-downloaded files are not re-downloaded
- Existing ZIPs are not re-created

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `NOTION_TOKEN not set` | Set env var or edit `config.py` |
| `404 Not Found` from Notion | Check `NOTION_DATABASE_ID` is correct |
| `403 Forbidden` from Notion | Share the database with your integration |
| Drive download fails | Check if file requires login — may need to share publicly |
| Upload `Select` vs `Checkbox` | The script auto-detects the `Upload` property type |
| Chrome driver error | Run `pip install --upgrade webdriver-manager` |

---

## state.json Example

```json
{
  "abc123def456-...": {
    "page_id": "abc123def456-...",
    "video_name": "Yellow",
    "age_group": "under 3",
    "category": "Colors",
    "drive_link": "https://drive.google.com/file/d/1Tl9...",
    "pipeline_status": "uploaded",
    "local_file": "downloads/Yellow.mp4",
    "batch": "Batch_01",
    "job_id": "job-uuid-here",
    "upload_date": "2026-04-20",
    "updated_at": "2026-04-20T17:45:00"
  }
}
```
