# Running Uploader in VS Code

## Quick Setup

### 1. Open the project in VS Code

```bash
code "C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard"
```

Or use File > Open Folder

### 2. Install Dependencies

**Option A: Using VS Code Terminal**
1. Press `Ctrl + ~` to open terminal
2. Run: `pip install -r requirements-uploader.txt`

**Option B: Using Tasks**
1. Press `Ctrl + Shift + B` (Run Build Task)
2. Select "Install Dependencies"
3. Wait for completion

### 3. Run the Auto Uploader

#### Method 1: Using Run/Debug (Easiest)
1. Click the **Run** icon in left sidebar (or press `Ctrl + Shift + D`)
2. Select "Auto Uploader (Full Automation)" from dropdown
3. Click the green play button
4. Terminal opens and script runs

#### Method 2: Using Tasks
1. Press `Ctrl + Shift + P`
2. Type "Run Task"
3. Select "Run Auto Uploader"
4. Script starts in terminal

#### Method 3: Direct Terminal
1. Press `Ctrl + ~` to open terminal
2. Type: `python cms_auto_uploader.py`
3. Press Enter

---

## What Happens When You Run

1. Browser opens automatically
2. Script logs in with your email/password
3. Finds each playlist and category
4. Uploads images to both thumbnail fields
5. Saves changes
6. Creates upload log file

---

## VS Code Debug/Run Options

In the Run/Debug dropdown (left sidebar), you can choose:

- **Auto Uploader (Full Automation)** ← Use this!
  - Logs in automatically
  - Uploads all images
  - ~30-45 minutes

- **Semi-Auto Uploader (Guided)**
  - Shows step-by-step instructions
  - You do the clicking
  - ~2-3 hours

- **Quick Start Helper**
  - Opens everything for manual upload
  - No automation

- **Image Processor**
  - Re-processes images if needed

- **CMS Matcher**
  - Re-generates upload checklist

---

## Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Open Run/Debug | `Ctrl + Shift + D` |
| Run Selected Task | `Ctrl + Shift + B` |
| Open Command Palette | `Ctrl + Shift + P` |
| Open Terminal | `Ctrl + ~` |
| Split Terminal | `Ctrl + Shift + \` |
| Stop Running Task | `Ctrl + C` |

---

## Step-by-Step

### First Time Setup:
1. Open VS Code
2. Press `Ctrl + Shift + B` → Install Dependencies
3. Wait for pip to finish
4. Done!

### Run the Uploader:
1. Press `Ctrl + Shift + D` (Run/Debug)
2. Select "Auto Uploader" from dropdown
3. Click green play button (▶️)
4. Watch it work in terminal!
5. Check upload log when done

### Monitor Progress:
- Terminal shows each step
- [OK] = Success
- [ERROR] = Problem
- [WARN] = Warning

---

## Troubleshooting in VS Code

### Script won't run
- Check Python is installed: `python --version`
- Check folder is open: File > Open Folder
- Reload VS Code: `Ctrl + R`

### "ChromeDriver not found"
- Install: `pip install webdriver-manager`
- Or download from https://chromedriver.chromium.org/
- Place in C:\Python\Scripts\

### Terminal shows error
- Look for [ERROR] messages
- Check internet connection
- Try again or use semi-auto mode

### Slow uploads
- Check internet speed
- Increase WAIT_TIMEOUT in script (line 20)
- Run at off-peak hours

---

## Terminal Tips

### Multiple Terminals
1. Open terminal: `Ctrl + ~`
2. Click `+` icon to add another
3. Organize side-by-side
4. Run multiple tasks

### Clear Terminal
Type: `clear` or `cls`

### View Upload Log
```bash
type processed_images\UPLOAD_LOG.json
```

---

## Common Tasks

### Just view the checklist
```bash
type processed_images\UPLOAD_CHECKLIST.txt
```

### View processing report
```bash
type processed_images\PROCESSING_REPORT.txt
```

### Check image files
```bash
dir processed_images\playlists
dir processed_images\characters
dir processed_images\categories
```

### View upload results
```bash
type processed_images\UPLOAD_LOG.json
```

---

## AutoLogin Configuration

Your credentials are stored in `cms_auto_uploader.py`:

```python
CMS_EMAIL = "Intern@babybillion.in"
CMS_PASSWORD = "57zQfDqS8ZN8bR2"
```

The script will:
1. Navigate to login page
2. Enter email automatically
3. Enter password automatically
4. Click login button
5. Wait for dashboard to load
6. Start uploading

---

## Performance Notes

- **Browser stays open** - Do not close it during upload
- **Takes ~30-45 minutes** - For all 92 images
- **Network speed matters** - Faster upload = faster completion
- **May pause** - Script waits for page load between uploads

---

## Advanced: Modify the Script

If login fails, you may need to update selectors:

1. Open `cms_auto_uploader.py` in VS Code
2. Find the `auto_login()` method (around line 60)
3. Update these selectors if needed:

```python
# Line for email input:
email_input = self.wait_for_element(By.CSS_SELECTOR, "input[type='email']")

# Line for password input:
password_input = self.wait_for_element(By.CSS_SELECTOR, "input[type='password']")

# Line for login button:
login_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Login')]")
```

Right-click element in browser > Inspect to find correct selectors.

---

## That's It!

You're ready to upload. Just:

```bash
python cms_auto_uploader.py
```

Or use the VS Code Run button for a more GUI experience.

Enjoy automated uploading! 🚀
