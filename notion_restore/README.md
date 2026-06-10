# Notion Trash Restore — AI Sprint

Restores all pages deleted **today** by **Akash Markad** from the "AI Sprint" Notion database.

## Prerequisites

- **Python 3.10+** (uses only the standard library — no `pip install` needed)
- A **Notion internal integration** with access to the AI Sprint database

## Setup

### 1. Create a Notion Integration

1. Go to [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **"+ New integration"**
3. Give it a name (e.g. "Trash Restorer")
4. Under **Capabilities**, ensure **Read content**, **Update content** are checked
5. Copy the **Internal Integration Secret** (`secret_...`)

### 2. Connect the Integration to Your Database

1. Open the **AI Sprint** database in Notion
2. Click the **···** menu (top-right) → **Connections** → **Add connections**
3. Search for your integration name and add it

### 3. Set the API Key

```powershell
set NOTION_API_KEY=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## Usage

### Preview (dry run — no changes made)
```powershell
python restore_trash.py --dry-run
```

### Restore for real
```powershell
python restore_trash.py
```

### If you already know the database ID
```powershell
python restore_trash.py --database-id <your-database-id>
```

## What It Does

1. **Searches** for the "AI Sprint" database via the Notion API
2. **Queries** all trashed pages in that database
3. **Filters** for pages last edited today (IST) by Akash Markad
4. **Restores** each matching page by setting `in_trash: false`
