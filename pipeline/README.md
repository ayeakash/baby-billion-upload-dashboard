# BabyBillion Upload Pipeline

Fully automated pipeline that downloads videos from Google Drive, compresses them, batches them, and uploads them to the BabyBillion admin dashboard — driven entirely from your Notion database.

---

## How it works

```
Notion DB  →  Download (3 threads)  →  Compress  →  Batch/Zip  →  Upload  →  Notion updated
```

1. Reads all videos marked **Status = "Ready to Upload"** and **Upload = "No"** from Notion
2. Downloads from Google Drive in parallel (3 threads)
3. Compresses any video over 20 MB using FFmpeg
4. Batches compressed files into ≤20 MB ZIP files with a CSV manifest
5. Uploads each batch to `admin.babybillion.in` via Selenium
6. Marks each video **Upload = "Yes"** in Notion with today's date

Progress is saved to `state.json` after every step — safe to interrupt and resume at any time.

---

## Requirements

| Requirement | Notes |
|-------------|-------|
| **Python 3.10+** | https://python.org |
| **Google Chrome** | https://www.google.com/chrome/ |
| **FFmpeg** | `winget install ffmpeg` or https://ffmpeg.org |
| **Internet access** | For Google Drive + Notion + admin site |

---

## First-time setup

**Windows:**
```bat
setup.bat
```

**Mac:**
```bash
chmod +x setup.sh run.sh   # only needed once
./setup.sh
```

This will:
- Create a Python virtual environment
- Install all Python dependencies
- Check for FFmpeg and Chrome
- Create `credentials.py` from the template

Then **edit `credentials.py`** and fill in:

```python
NOTION_TOKEN       = "secret_..."       # Notion integration token
NOTION_DATABASE_ID = "..."              # From your Notion DB URL
BB_USERNAME        = "your@email.com"   # Admin site login
BB_PASSWORD        = "yourpassword"
```

---

## Running the pipeline

**Windows:** `run.bat` · **Mac:** `./run.sh`

That's it. The script auto-pulls the latest code from GitHub, then runs the pipeline.
Chrome will open automatically when the first batch is ready to upload.

### Options

```bash
run.bat --headless    # Run Chrome in background (no visible window)
run.bat --status      # Print current state summary and exit
run.bat --dry-run     # Fetch from Notion but don't download/upload
# On Mac, replace run.bat with ./run.sh
```

---

## Resuming after interruption

The pipeline is **idempotent** — just run `run.bat` again. It will:
- Skip already-downloaded files
- Skip already-uploaded videos
- Re-attempt anything that previously failed

---

## Retrying failed uploads

There are three retry scripts depending on the failure type:

```bat
.venv\Scripts\activate.bat

# Retry videos marked "Failed to upload" in Notion (e.g. bad category, now fixed)
python retry_failed_notion.py --headless

# Retry videos marked "Failed" in Notion (older failures)
python retry_notion_failed.py --headless

# Retry local pipeline failures (no job ID, re-upload existing batches)
python retry_failed.py --headless
```

---

## Fixing corrupt state.json

If `state.json` becomes corrupted (e.g. after a force-quit):

```bat
.venv\Scripts\activate.bat
python fix_state.py
```

---

## File structure

```
notion_pipeline/
├── run.bat / run.sh           ← START HERE every time (Windows / Mac)
├── setup.bat / setup.sh       ← Run once on a new machine
├── credentials.py             ← Your secrets (never commit!)
├── credentials.example.py     ← Template for credentials.py
├── requirements.txt           ← Python dependencies
│
├── pipeline.py                ← Main orchestrator (parallel download + compress + upload)
├── retry_failed.py            ← Re-uploads failed batches (local state failures)
├── retry_failed_notion.py     ← Retries "Failed to upload" videos from Notion
├── retry_notion_failed.py     ← Retries "Failed" status videos from Notion
├── fix_state.py               ← Repairs corrupted state.json
│
├── config.py                  ← Settings (batch size, URLs, column mappings)
├── categories mapping.csv     ← Age group → category mapping for the admin site
├── category_mapper.py         ← Loads CSV and resolves Notion categories
├── dedup_utils.py             ← Unified video deduplication (name+age normalization)
├── sanity_checker.py          ← Validates videos before pipeline processing
├── state.json                 ← Pipeline progress tracker (auto-generated, local)
│
├── downloader.py              ← Google Drive download logic (files + folders)
├── compressor.py              ← FFmpeg video compression (>20 MB → <20 MB)
├── batcher.py                 ← Groups videos into ≤30 MB batches with CSV
├── zipper.py                  ← Creates ZIP archives for upload
├── uploader.py                ← Selenium upload to admin dashboard
├── notion_client.py           ← Notion API read/write (includes multi-PC claim)
├── state_manager.py           ← Thread-safe state.json manager
├── sync_notion.py             ← Sync upload status back to Notion
│
├── downloads/                 ← Downloaded MP4 files (auto-cleaned)
├── batches/                   ← Batch CSVs and ZIPs (auto-cleaned)
└── logs/                      ← Timestamped run logs
```

---

## Running on multiple PCs

The pipeline works on **Windows and Mac**. Notion is the shared source of truth — each machine queries the same Notion database, and the `Upload = Yes/No` flag prevents duplicates.

### Setting up a new machine

**Mac:**
```bash
# 1. Clone the repo
git clone https://github.com/ayeakash/notion-pipeline.git
cd notion-pipeline

# 2. Run first-time setup
chmod +x setup.sh run.sh
./setup.sh

# 3. Edit credentials.py with your Notion token + admin login
nano credentials.py

# 4. Run the pipeline (auto-pulls latest code from GitHub)
./run.sh
```

**Windows:**
```bat
git clone https://github.com/ayeakash/notion-pipeline.git
cd notion-pipeline
setup.bat
notepad credentials.py
run.bat
```

### How sync works

- `run.bat` / `run.sh` auto-pulls the latest code from GitHub before each run
- Each machine has its own local `state.json` (not shared)
- **Notion** tracks which videos are uploaded — both machines read the same database
- As long as you don't run both machines at the exact same time, there's zero risk of duplicates

### If code changes are made on one machine

Push to GitHub, and the other machine auto-receives them on next run:

```bash
git add -A
git commit -m "description of change"
git push
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Cannot retrieve public link" | The Google Drive file isn't shared publicly — set it to "Anyone with the link" |
| Chrome doesn't open | Make sure Chrome is installed; try `run.bat --headless` for background mode |
| FFmpeg not found | Run `winget install ffmpeg`, then restart your terminal |
| `state.json` corrupted | Run `python fix_state.py` |
| Upload fails repeatedly | Run `python retry_failed.py` — it retries only failed batches |
