# BabyBillion Upload Dashboard

A local Flask dashboard + pipeline that moves kids' videos from **Notion / Google Drive / YouTube** into the **BabyBillion CMS** (admin.babybillion.in), in reviewable ~100 MB batches.

```
                ┌─ Notion "Ready to Upload" ─┐
Sources ────────┼─ BFB (teachers) Notion DB ─┼──▶ download ▶ compress ▶ batch (CSV+ZIP)
                └─ YouTube channels (yt-dlp) ┘         │
                                                       ▼
              Dashboard review ◀── batches.json ── Selenium upload to CMS
                     │                                 │
                     └── finalize ──▶ Notion write-back + local cleanup
```

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp pipeline/credentials.example.py pipeline/credentials.py   # fill in real values
.venv/bin/python app.py                                      # → http://127.0.0.1:5050
```

`ffmpeg` must be on PATH for compression (`brew install ffmpeg`).

Launchers: `run_dashboard.sh` (macOS/Linux), `run_dashboard.bat` (Windows),
`run_dashboard.command` (macOS double-click).

## Layout

| Path | What it is |
|---|---|
| `app.py` | Flask server — all dashboard API routes (port 5050) |
| `batch_manager.py` | Batch lifecycle state machine + upload/pipeline threads |
| `yt_channel_manager.py` | YouTube channel tracking/download/batching (yt-dlp) |
| `upload_history.py` | Append-only audit log (`upload_history.jsonl`) |
| `auto_upload.py` | CLI: batch + upload a folder of videos without the UI |
| `procutils.py` | Cross-platform process kill/suspend/open-folder helpers |
| `templates/` | `index.html` (main UI), `bfb.html`, `channels.html` |
| `pipeline/` | Core engine: `pipeline.py`, `downloader`, `compressor`, `batcher`, `zipper`, `uploader` (Selenium), `notion_client`, `state_manager`, `fslock` |
| `tools/archive/` | Dead one-off incident scripts, kept for reference |
| `download_system/`, `playlist uploads/`, `notion_restore/` | Standalone side tools, not wired into the dashboard |

## State files (all gitignored)

- `state.json` — per-video pipeline status, keyed by Notion page id (+`___ln_Hi`/`___ln_En` language suffix)
- `batches.json` — batch-level status: `pending_first_review → pending_second_review → finalized` (+ `upload_failed`)
- `upload_history.jsonl` — permanent record of every upload attempt

Writers go through `pipeline/fslock.py` (cross-process file lock) — don't edit these files by hand while anything is running.

## Credentials

All secrets live in `pipeline/credentials.py` (gitignored) or env vars:
`NOTION_TOKEN`, `NOTION_DATABASE_ID`, `BB_USERNAME`, `BB_PASSWORD`.
Never hardcode credentials in scripts — this repo is public.

Note: `pipeline/config.py` has `NOTION_READ_ONLY = True` by default, which makes
**all Notion write-backs no-ops** (state.json is then the only source of truth).
Set it to `False` to enable real Notion sync.
