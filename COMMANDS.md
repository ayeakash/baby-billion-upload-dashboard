# Commands to Run the Uploader

## Test First (Safe - Only 1 Character)

### **In PowerShell or VS Code Terminal:**

```bash
cd C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard
python test_single_upload.py
```

**What it does:**
- Logs in automatically ✓
- Searches for "Guddi" character ✓
- Uploads ONE test image ✓
- Saves the change ✓
- Takes ~2-3 minutes ✓

**If test succeeds:**
- See "SUCCESS" message
- Image uploaded to CMS
- Ready for full upload

**If test fails:**
- See error message
- Fix issue listed
- Try again

---

## Run Full Automatic Uploader

### **When test passes, run:**

```bash
python cms_auto_uploader.py
```

**What it does:**
- Logs in automatically ✓
- Uploads ALL 15 playlists ✓
- Uploads ALL 58 categories ✓
- Uploads ALL 19 characters ✓
- Creates upload log ✓
- Takes ~30-45 minutes ✓

---

## Step-by-Step Instructions

### **Option A: Using PowerShell**

1. **Open PowerShell:**
   - Press `Win + R`
   - Type: `powershell`
   - Press Enter

2. **Go to project folder:**
   ```bash
   cd C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard
   ```

3. **Install dependencies (first time only):**
   ```bash
   pip install -r requirements-uploader.txt
   ```

4. **Run test:**
   ```bash
   python test_single_upload.py
   ```

5. **When test passes, run full uploader:**
   ```bash
   python cms_auto_uploader.py
   ```

---

### **Option B: Using VS Code**

1. **Open VS Code:**
   ```bash
   code C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard
   ```

2. **Open Terminal:**
   - Press `Ctrl + ~`

3. **Install dependencies (first time only):**
   ```bash
   pip install -r requirements-uploader.txt
   ```

4. **Run test:**
   ```bash
   python test_single_upload.py
   ```

5. **Or use Run button (if configured):**
   - Press `Ctrl + Shift + D`
   - Select "Test Single Upload"
   - Click ▶️

---

## Command Cheat Sheet

```bash
# Go to folder
cd C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard

# Install (first time)
pip install -r requirements-uploader.txt

# Test with 1 character
python test_single_upload.py

# Full upload (all images)
python cms_auto_uploader.py

# Semi-auto (guided)
python cms_semi_auto_uploader.py

# Quick start (manual)
python quick_start_uploader.py

# View upload results
type processed_images\UPLOAD_LOG.json

# View checklist
type processed_images\UPLOAD_CHECKLIST.txt
```

---

## What Happens When You Run Test

**Terminal Output:**

```
================================================================================
TEST UPLOADER - SINGLE CHARACTER UPLOAD
================================================================================

[OK] Found image: guddi.jpg (65.4KB)
[*] Will upload to: Guddi

[*] Initializing Chrome WebDriver...
[OK] Chrome WebDriver initialized

[Step 1/5] Navigating to login page...
[OK] Login page loaded

[Step 2/5] Logging in automatically...
  [OK] Email entered: Intern@babybillion.in
  [OK] Password entered
  [OK] Login button clicked
  [*] Waiting for dashboard to load...
[OK] Login successful!

[Step 3/5] Navigating to categories...
[OK] Categories page loaded

[Step 4/5] Searching for 'Guddi'...
[OK] Searched for: Guddi

[Step 5/5] Uploading image...
  [OK] Edit button clicked
  [*] Found 2 file input field(s)
  [OK] Uploaded to field 1
  [OK] Uploaded to field 2
  [*] Looking for save button...
  [OK] Save button clicked

================================================================================
[SUCCESS] TEST UPLOAD COMPLETE!
================================================================================

Press ENTER to close browser...
```

---

## Troubleshooting

### **"ChromeDriver not found"**
```bash
pip install webdriver-manager
```
Then run again

### **"Module not found: selenium"**
```bash
pip install selenium
```

### **"File not found"**
Make sure you're in the correct folder:
```bash
cd C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard
```

### **"Connection refused"**
- Check internet connection
- Try again
- If still fails, use semi-auto mode

### **"Login failed"**
- Check credentials in script
- Check CMS website is up
- Try semi-auto mode

---

## Test Results

### **Success Means:**
```
[SUCCESS] TEST UPLOAD COMPLETE!
```
- Auto-login works ✓
- CMS navigation works ✓
- Image upload works ✓
- Save function works ✓
- Ready for full upload ✓

### **Failure Means:**
```
[ERROR] Test failed: ...
```
- See error message
- Check troubleshooting above
- Try semi-auto mode instead

---

## Quick Commands Summary

**Test (1 image):**
```bash
python test_single_upload.py
```

**Full upload (92 images):**
```bash
python cms_auto_uploader.py
```

**Semi-auto (guided):**
```bash
python cms_semi_auto_uploader.py
```

---

## After Upload Completes

Check results:
```bash
type processed_images\UPLOAD_LOG.json
```

View summary:
```bash
type processed_images\PROCESSING_REPORT.txt
```

---

## Done!

When you see:
```
[SUCCESS] TEST UPLOAD COMPLETE!
```

Or:
```
[OK] IMAGE PROCESSING COMPLETE
```

Your uploads are done! ✓
