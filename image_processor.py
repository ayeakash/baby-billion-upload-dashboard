"""
Image processor for Baby Billion CMS
- Downloads/reads images from folders
- Resizes to appropriate dimensions (1:1 for playlists, 3:4 for categories/characters)
- Compresses to max 200KB
- Matches filenames with CMS entries (handles typos)
- Prepares for CMS upload
"""

import os
import shutil
from PIL import Image
from pathlib import Path
import json
from difflib import SequenceMatcher
import io

# Configuration
PLAYLISTS_SOURCE = r"C:\Users\Aashitha\Downloads\playlists-20260807T064246Z-1-001\playlists"
CHARACTERS_SOURCE = r"C:\Users\Aashitha\Downloads\characters-20260807T064240Z-1-001\characters"
CATEGORIES_SOURCE = r"C:\Users\Aashitha\Downloads\category thumbnails-20260807T064239Z-1-001\category thumbnails"

OUTPUT_BASE = r"C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard\processed_images"

# Create output directories
PLAYLISTS_OUTPUT = os.path.join(OUTPUT_BASE, "playlists")
CHARACTERS_OUTPUT = os.path.join(OUTPUT_BASE, "characters")
CATEGORIES_OUTPUT = os.path.join(OUTPUT_BASE, "categories")

# Image compression settings
MAX_FILE_SIZE = 200 * 1024  # 200KB in bytes
QUALITY = 95  # Start with high quality

# Aspect ratios
PLAYLIST_RATIO = (1, 1)  # 1:1
CHARACTER_RATIO = (3, 4)  # 3:4
CATEGORY_RATIO = (1, 1)   # 1:1 (changed from 3:4)

# Common size options for each ratio
PLAYLIST_SIZE = (500, 500)
CHARACTER_SIZE = (375, 500)
CATEGORY_SIZE = (500, 500)  # Changed from (375, 500) to (500, 500)


def ensure_output_dirs():
    """Create output directories"""
    for directory in [PLAYLISTS_OUTPUT, CHARACTERS_OUTPUT, CATEGORIES_OUTPUT]:
        os.makedirs(directory, exist_ok=True)
        print(f"[OK] Created directory: {directory}")


def resize_image_to_ratio(image_path, target_width, target_height, output_path):
    """
    Resize image to target ratio, padding with white space if necessary
    """
    img = Image.open(image_path).convert('RGB')

    # Calculate aspect ratios
    img_ratio = img.width / img.height
    target_ratio = target_width / target_height

    # Calculate new size maintaining aspect ratio
    if img_ratio > target_ratio:
        # Image is wider than target ratio
        new_height = target_height
        new_width = int(new_height * img_ratio)
    else:
        # Image is taller than target ratio
        new_width = target_width
        new_height = int(new_width / img_ratio)

    # Resize image
    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Create new image with white background and proper dimensions
    final_img = Image.new('RGB', (target_width, target_height), 'white')

    # Calculate position to center the image
    x = (target_width - new_width) // 2
    y = (target_height - new_height) // 2

    # Paste resized image onto white background
    final_img.paste(img_resized, (x, y))

    return final_img


def compress_image(image, output_path, max_size=MAX_FILE_SIZE):
    """
    Compress image to max file size using WebP format
    WebP provides better compression than JPEG/PNG
    """
    quality = QUALITY
    format_type = 'WEBP'

    while quality > 5:
        # Save to bytes
        img_bytes = io.BytesIO()
        try:
            image.save(img_bytes, format=format_type, quality=quality, method=6)
        except:
            # Fallback without method parameter
            image.save(img_bytes, format=format_type, quality=quality)

        file_size = img_bytes.tell()

        if file_size <= max_size:
            # Write to file with correct extension
            final_path = output_path.replace('.jpg', '.webp').replace('.png', '.webp')
            with open(final_path, 'wb') as f:
                f.write(img_bytes.getvalue())
            return file_size

        quality -= 5

    # If still too large, save at minimum quality
    img_bytes = io.BytesIO()
    image.save(img_bytes, format=format_type, quality=5, method=6)
    final_path = output_path.replace('.jpg', '.webp').replace('.png', '.webp')
    with open(final_path, 'wb') as f:
        f.write(img_bytes.getvalue())

    return img_bytes.tell()


def process_image(source_path, output_path, width, height):
    """
    Resize and compress an image
    """
    try:
        # Resize to aspect ratio
        resized_img = resize_image_to_ratio(source_path, width, height, output_path)

        # Compress
        file_size = compress_image(resized_img, output_path)

        # Convert to KB for display
        size_kb = file_size / 1024
        size_status = "[OK]" if file_size <= MAX_FILE_SIZE else "[WARN]"

        return True, size_kb, size_status
    except Exception as e:
        return False, 0, f"[ERROR] {str(e)}"


def similarity_ratio(a, b):
    """
    Calculate similarity between two strings (0-1, where 1 is identical)
    """
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def find_best_match(filename, candidates, threshold=0.6):
    """
    Find best matching candidate for a filename, handling typos
    Returns (best_match, similarity_score)
    """
    filename_clean = os.path.splitext(filename)[0].replace('_', ' ').lower()

    best_match = None
    best_score = 0

    for candidate in candidates:
        candidate_clean = candidate.replace('_', ' ').lower()
        score = similarity_ratio(filename_clean, candidate_clean)

        if score > best_score:
            best_score = score
            best_match = candidate

    if best_score >= threshold:
        return best_match, best_score

    return None, best_score


def process_playlists():
    """Process playlist images (1:1 ratio)"""
    print("\n" + "="*60)
    print("PROCESSING PLAYLISTS (1:1 Ratio)")
    print("="*60)

    if not os.path.exists(PLAYLISTS_SOURCE):
        print(f"✗ Source directory not found: {PLAYLISTS_SOURCE}")
        return {}

    results = {}

    for filename in os.listdir(PLAYLISTS_SOURCE):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            source_path = os.path.join(PLAYLISTS_SOURCE, filename)
            output_filename = os.path.splitext(filename)[0] + '.webp'
            output_path = os.path.join(PLAYLISTS_OUTPUT, output_filename)

            success, size, status = process_image(source_path, output_path, *PLAYLIST_SIZE)

            name = os.path.splitext(filename)[0]
            results[name] = {
                'filename': output_filename,
                'path': output_path,
                'size_kb': size,
                'status': status,
                'success': success
            }

            print(f"{status} {name:30} -> {size:6.1f}KB")

    return results


def process_characters():
    """Process character images (3:4 ratio)"""
    print("\n" + "="*60)
    print("PROCESSING CHARACTERS (3:4 Ratio)")
    print("="*60)

    if not os.path.exists(CHARACTERS_SOURCE):
        print(f"✗ Source directory not found: {CHARACTERS_SOURCE}")
        return {}

    results = {}

    for filename in os.listdir(CHARACTERS_SOURCE):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            source_path = os.path.join(CHARACTERS_SOURCE, filename)
            output_filename = os.path.splitext(filename)[0] + '.webp'
            output_path = os.path.join(CHARACTERS_OUTPUT, output_filename)

            success, size, status = process_image(source_path, output_path, *CHARACTER_SIZE)

            name = os.path.splitext(filename)[0]
            results[name] = {
                'filename': output_filename,
                'path': output_path,
                'size_kb': size,
                'status': status,
                'success': success
            }

            print(f"{status} {name:30} -> {size:6.1f}KB")

    return results


def process_categories():
    """Process category images (3:4 ratio)"""
    print("\n" + "="*60)
    print("PROCESSING CATEGORIES (3:4 Ratio)")
    print("="*60)

    if not os.path.exists(CATEGORIES_SOURCE):
        print(f"✗ Source directory not found: {CATEGORIES_SOURCE}")
        return {}

    results = {}

    for filename in os.listdir(CATEGORIES_SOURCE):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            source_path = os.path.join(CATEGORIES_SOURCE, filename)
            output_filename = os.path.splitext(filename)[0] + '.webp'
            output_path = os.path.join(CATEGORIES_OUTPUT, output_filename)

            success, size, status = process_image(source_path, output_path, *CATEGORY_SIZE)

            name = os.path.splitext(filename)[0]
            results[name] = {
                'filename': output_filename,
                'path': output_path,
                'size_kb': size,
                'status': status,
                'success': success
            }

            print(f"{status} {name:30} -> {size:6.1f}KB")

    return results


def save_mapping_report(playlists, characters, categories):
    """Save a report of all processed images and their mappings"""
    report_path = os.path.join(OUTPUT_BASE, "PROCESSING_REPORT.txt")

    with open(report_path, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("IMAGE PROCESSING REPORT\n")
        f.write("=" * 80 + "\n\n")

        # Playlists
        f.write("PLAYLISTS (1:1 Ratio)\n")
        f.write("-" * 80 + "\n")
        for name, info in sorted(playlists.items()):
            f.write(f"{name:30} -> {info['filename']:30} ({info['size_kb']:6.1f}KB) {info['status']}\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("CHARACTERS (3:4 Ratio)\n")
        f.write("-" * 80 + "\n")
        for name, info in sorted(characters.items()):
            f.write(f"{name:30} -> {info['filename']:30} ({info['size_kb']:6.1f}KB) {info['status']}\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("CATEGORIES (3:4 Ratio)\n")
        f.write("-" * 80 + "\n")
        for name, info in sorted(categories.items()):
            f.write(f"{name:30} -> {info['filename']:30} ({info['size_kb']:6.1f}KB) {info['status']}\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("SUMMARY\n")
        f.write("-" * 80 + "\n")
        f.write(f"Total Playlists: {len(playlists)}\n")
        f.write(f"Total Characters: {len(characters)}\n")
        f.write(f"Total Categories: {len(categories)}\n")
        f.write(f"Total Images: {len(playlists) + len(characters) + len(categories)}\n")

    print(f"\n[OK] Report saved to: {report_path}")


def main():
    """Main function"""
    print("\n" + "="*60)
    print("BABY BILLION IMAGE PROCESSOR")
    print("="*60)

    # Create output directories
    ensure_output_dirs()

    # Process all image types
    playlists = process_playlists()
    characters = process_characters()
    categories = process_categories()

    # Save report
    save_mapping_report(playlists, characters, categories)

    print("\n" + "="*60)
    print("[OK] IMAGE PROCESSING COMPLETE")
    print("="*60)
    print(f"\nProcessed images are in: {OUTPUT_BASE}")
    print(f"\nReady to upload to CMS:")
    print(f"  - Playlists: {PLAYLISTS_OUTPUT}")
    print(f"  - Characters: {CHARACTERS_OUTPUT}")
    print(f"  - Categories: {CATEGORIES_OUTPUT}")
    print("\nNext step: Run cms_uploader.py to upload to CMS")


if __name__ == "__main__":
    main()
