# 🔔 Slack Nightly Summary — Baby Billion Pipeline

Automatically sends a daily content pipeline summary to Slack at **11 PM IST** every night.

```
📋 Daily Summary — 20 July 2026
──────────────────────────────────
📹  Number of videos uploaded — 142
✅  Ready to upload — 8
🔔  Approval pending [After audio] — 3
🎙️  Audio pending — 12
🔧  Corrections pending — 5
👀  Review pending — 7
🚧  Content WIP — 15

🎯  This week's goal — 50
📊  WTD content uploaded — 14
📈  MTD content uploaded — 38
```

---

## ⚡ Quick Setup (3 steps)

### 1. Create a Slack Webhook

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"** → **"From scratch"**
3. Name: `Baby Billion Bot`, pick your workspace
4. Left sidebar → **"Incoming Webhooks"** → Toggle **ON**
5. **"Add New Webhook to Workspace"** → Select a channel
6. Copy the Webhook URL

### 2. Add Credentials

Edit `slack_notifier/credentials.py`:

```python
SLACK_WEBHOOK_URL  = "https://hooks.slack.com/services/T.../B.../xxxx"  # paste here
NOTION_TOKEN       = "ntn_..."    # same as pipeline/credentials.py
NOTION_DATABASE_ID = "34463..."   # same as pipeline/credentials.py
```

### 3. Test It

```bash
# Preview the message in terminal (no Slack post)
cd slack_notifier
python slack_summary.py --dry-run

# Verify webhook connectivity
python slack_summary.py --test

# Send for real
python slack_summary.py
```

---

## ⏰ Set Up Nightly Schedule

```bash
# Install cron job (runs at 11 PM IST every night)
chmod +x setup_cron.sh
./setup_cron.sh install

# Check status
./setup_cron.sh status

# Remove cron job
./setup_cron.sh remove
```

To change the time, edit `CRON_SCHEDULE` in `setup_cron.sh`. Common values:

| IST Time | UTC Cron |
|----------|----------|
| 10:00 PM | `30 16 * * *` |
| 10:30 PM | `0 17 * * *` |
| 11:00 PM | `30 17 * * *` |
| 11:30 PM | `0 18 * * *` |

---

## 🎯 Configuring the Weekly Goal

Override via command line:
```bash
python slack_summary.py --goal 75
```

Or edit `WEEKLY_GOAL` in `slack_summary.py` (line ~58).

---

## 📊 Status Mapping

The script maps Notion `Status` values to summary labels. Edit `STATUS_MAP` in `slack_summary.py` if your Notion uses different names:

```python
STATUS_MAP = {
    "Ready to upload":                ["Ready to Upload", "Ready To Upload"],
    "Approval pending [After audio]": ["Approval Pending", "Approval pending"],
    "Audio pending":                  ["Audio Pending", "Audio pending"],
    "Corrections pending":            ["Corrections Pending", "Corrections pending"],
    "Review pending":                 ["Review Pending", "Review pending"],
    "Content WIP":                    ["Content WIP", "Content wip", "WIP"],
}
```

Use `--dry-run` to see what status values actually exist in your database — they're listed at the bottom of the output.

---

## 📁 Files

```
slack_notifier/
├── credentials.py           # Your secrets (gitignored)
├── credentials.example.py   # Template for reference
├── slack_summary.py         # Main script
├── setup_cron.sh            # Cron job installer
├── requirements.txt         # Python deps
├── README.md                # This file
└── logs/                    # Cron output logs (auto-created)
    └── slack_summary.log
```
