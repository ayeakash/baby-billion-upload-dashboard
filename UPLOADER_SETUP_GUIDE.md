# CMS Auto Uploader Setup Guide

## Option 1: Automated Uploader (Recommended)

### Installation

1. Install required packages:
```bash
pip install -r requirements-uploader.txt
```

2. Download ChromeDriver:
   - Download from: https://chromedriver.chromium.org/
   - Choose version matching your Chrome version
   - Place in your Python Scripts folder or add to PATH

### Running the Uploader

```bash
python cms_auto_uploader.py
```

**What happens:**
1. Chrome browser opens automatically
2. Navigate to the login screen (it will appear)
3. Log in manually with your credentials
4. After login, the script automatically:
   - Finds each playlist/category
   - Uploads the matched image
   - Saves the changes
5. Progress is shown in console

### Features

- **Automatic login detection** - Waits for you to log in
- **Smart search** - Finds playlists/categories by name
- **Dual upload** - Uploads to both thumbnail fields
- **Auto-save** - Clicks save after each upload
- **Upload log** - Creates UPLOAD_LOG.json with results
- **Browser visible** - See exactly what's happening

### Troubleshooting

**"ChromeDriver not found"**
- Download ChromeDriver from https://chromedriver.chromium.org/
- Place it in C:\Python\Scripts\ or add directory to PATH
- Or specify path in script

**"Could not find file input element"**
- The CMS might use different selectors
- Edit the `thumbnail_selectors` list in the script
- Check CMS HTML structure and update selectors

**Upload times out**
- Network might be slow
- Increase `WAIT_TIMEOUT` in the script (default: 20 seconds)
- Check internet connection

**Images not saving**
- Verify images are in processed_images/ folders
- Check image file names match CMS entry names
- Manual fallback: Use Option 2 below

---

## Option 2: Semi-Automatic Uploader

### Installation

```bash
pip install selenium
```

### Running

```bash
python cms_semi_auto_uploader.py
```

This version:
- Opens browser with guided steps
- Shows you what to do at each step
- Waits for you to verify before proceeding
- Logs all actions
- Slower but more reliable

---

## Option 3: Manual Upload (Fallback)

If automation doesn't work, use the manual checklist:

1. Open **UPLOAD_CHECKLIST.txt**
2. For each entry:
   - Go to: https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/playlists (or categories)
   - Find the entry by name
   - Click "Edit"
   - Upload image to **BOTH** thumbnail fields
   - Click "Save"

The checklist shows:
- Exact image file location (copy full path)
- CMS entry name
- Match quality percentage

---

## File Organization

```
processed_images/
├── playlists/              # 15 images
├── characters/             # 19 images
├── categories/             # 58 images
├── image_matches.json      # Used by auto-uploader
└── UPLOAD_LOG.json         # Created after upload
```

---

## CMS URLs

- **Playlists:** https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/playlists
- **Categories:** https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories

---

## Important Notes

- All images are already matched (100% accuracy)
- All images are compressed (<200KB)
- All images have correct aspect ratios
- Uploader handles multiple image formats
- Original files untouched - only processed images used

---

## Getting Help

1. Check console output for specific errors
2. Verify image files exist in processed_images/
3. Check image names match CMS entries
4. Try manual upload if automation fails
5. Check UPLOAD_LOG.json for detailed results

---

## Script Options

### Auto Uploader

```python
# In cms_auto_uploader.py, line to change:
uploader = CMSUploader(headless=False)  # Set to True for headless mode

# headless=False   → Browser window visible (recommended)
# headless=True    → No window, faster but harder to debug
```

### Timeouts

```python
# In cms_auto_uploader.py:
WAIT_TIMEOUT = 20        # Seconds to wait for element
SHORT_WAIT = 5           # Seconds between actions

# Increase if CMS is slow, decrease if timeout too long
```
