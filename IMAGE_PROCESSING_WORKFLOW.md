# Baby Billion Image Processing & CMS Upload Workflow

## Overview
This workflow processes images from three sources, resizes them to appropriate dimensions, compresses them to max 200KB, matches them to CMS entries, and provides upload instructions.

## Quick Start

### Step 1: Process Images
Run the image processor to resize and compress all images:

```bash
python image_processor.py
```

This will:
- ✓ Read all images from source folders
- ✓ Resize to correct aspect ratios (1:1 for playlists, 3:4 for categories/characters)
- ✓ Compress to max 200KB
- ✓ Save processed images to `processed_images/` folder

**Output:**
- `processed_images/playlists/` - 1:1 ratio images
- `processed_images/characters/` - 3:4 ratio images  
- `processed_images/categories/` - 3:4 ratio images
- `processed_images/PROCESSING_REPORT.txt` - Detailed report of all processed images

---

### Step 2: Match Images to CMS Entries
Run the matcher to find which CMS entries match which images:

```bash
python cms_matcher_and_uploader.py
```

This will:
- ✓ Compare image filenames with CMS entry names
- ✓ Handle typos and naming variations (fuzzy matching)
- ✓ Generate a matching report
- ✓ Create an upload checklist

**Output:**
- `processed_images/UPLOAD_CHECKLIST.txt` - Step-by-step upload guide
- `processed_images/image_matches.json` - Machine-readable matching data
- Console output showing match quality for each image

**Match Quality Legend:**
- ✓ MATCH (90%+) - Automatic match, high confidence
- ⚠ FUZZY (75-89%) - Likely match, verify before uploading
- ✗ NO MATCH (<75%) - Manual review needed

---

### Step 3: Upload to CMS
Upload images to the CMS using the checklist:

#### For Playlists:
1. Go to: https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/playlists
2. Find the playlist from the checklist
3. Click "Edit"
4. Under "Thumbnails (two designs)" - upload the matched image to BOTH fields
5. Click Save

#### For Categories:
1. Go to: https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories
2. Find the category from the checklist
3. Click "Edit"
4. Under "Thumbnails (two designs)" - upload the matched image to BOTH fields
5. Click Save

#### For Characters:
- Characters are typically uploaded as part of playlists if they belong to a playlist
- Some characters might be standalone - check CMS to see where they belong

---

## Image Specifications

### Playlists
- **Aspect Ratio:** 1:1 (square)
- **Processing Size:** 500×500 pixels
- **Max File Size:** 200KB
- **Format:** PNG

### Categories & Characters
- **Aspect Ratio:** 3:4 (portrait)
- **Processing Size:** 375×500 pixels
- **Max File Size:** 200KB
- **Format:** PNG

### Compression Details
- Images larger than 200KB are automatically compressed
- Compression preserves quality while staying under the limit
- All images are converted to PNG format for consistency

---

## File Structure

```
baby-billion-upload-dashboard/
├── image_processor.py                      # Main image processing script
├── cms_matcher_and_uploader.py             # Matching and checklist generator
├── IMAGE_PROCESSING_WORKFLOW.md            # This file
├── processed_images/                       # Output directory
│   ├── playlists/                          # 1:1 playlist images
│   ├── characters/                         # 3:4 character images
│   ├── categories/                         # 3:4 category images
│   ├── PROCESSING_REPORT.txt               # Processing summary
│   ├── UPLOAD_CHECKLIST.txt                # Upload guide
│   └── image_matches.json                  # Machine-readable matches
```

---

## Troubleshooting

### Image Not Matching
- Check the spelling of the image filename
- Review `image_matches.json` to see what it's being matched to
- Common issues:
  - Underscores vs spaces (handled automatically)
  - Typos in filenames (fuzzy matching tries to handle this)
  - Different naming conventions

### Image Too Large After Compression
- If an image is still >200KB after processing, check:
  - Original image quality/size
  - The script will show warnings for files over the limit
  - Try processing manually with different quality settings

### Upload Not Working
- Ensure you're logged into the CMS
- Check that both thumbnail fields are being filled
- Verify the image is in the correct format (PNG)
- Try uploading manually if script-based upload fails

---

## Manual Adjustments

If you need to:
1. **Adjust image mappings:** Edit `CATEGORY_NAMES`, `PLAYLIST_NAMES`, or `CHARACTER_NAMES` in `cms_matcher_and_uploader.py`
2. **Change compression quality:** Edit `QUALITY` variable in `image_processor.py`
3. **Change image dimensions:** Edit `PLAYLIST_SIZE`, `CHARACTER_SIZE`, `CATEGORY_SIZE` in `image_processor.py`

---

## Requirements

```
Pillow (PIL)
Python 3.7+
```

Install requirements:
```bash
pip install Pillow
```

---

## Notes

- **Aspect Ratio Handling:** Images are resized while maintaining aspect ratio, with white padding added to reach exact dimensions
- **Quality Preservation:** Compression starts at 95% quality and decreases gradually to stay under 200KB limit
- **Fuzzy Matching:** Uses sequence matching to handle common typos and naming variations
- **Batch Processing:** All images are processed in one run for consistency

---

## Support

For issues or questions:
1. Check `PROCESSING_REPORT.txt` for processing details
2. Review `UPLOAD_CHECKLIST.txt` for specific upload issues
3. Verify source image quality and format
