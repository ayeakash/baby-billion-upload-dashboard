"""
Create 3:4 aspect ratio images (375x500px) for Home View upload
"""

import os
from PIL import Image

BASE_DIR = r"C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard"
SOURCE_DIR = os.path.join(BASE_DIR, "processed_images")
OUTPUT_DIR = os.path.join(BASE_DIR, "processed_images_34")

TARGET_WIDTH = 375
TARGET_HEIGHT = 500
QUALITY_SETTINGS = [95, 85, 75, 65, 55, 45, 35, 25, 15, 5]
MAX_SIZE_KB = 200

def create_34_image(input_path, output_path):
    """Convert image to 3:4 (375x500) with white padding"""
    try:
        img = Image.open(input_path)

        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Create new image with white background
        new_img = Image.new('RGB', (TARGET_WIDTH, TARGET_HEIGHT), 'white')

        # Calculate dimensions to maintain aspect ratio
        img_ratio = img.width / img.height
        target_ratio = TARGET_WIDTH / TARGET_HEIGHT  # 375/500 = 0.75

        if img_ratio > target_ratio:
            # Image is wider, fit by width
            new_width = TARGET_WIDTH
            new_height = int(TARGET_WIDTH / img_ratio)
        else:
            # Image is taller, fit by height
            new_height = TARGET_HEIGHT
            new_width = int(TARGET_HEIGHT * img_ratio)

        # Resize image
        img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Calculate position to center the image
        x_offset = (TARGET_WIDTH - new_width) // 2
        y_offset = (TARGET_HEIGHT - new_height) // 2

        # Paste resized image onto white background
        new_img.paste(img_resized, (x_offset, y_offset))

        # Compress to WebP with quality reduction
        for quality in QUALITY_SETTINGS:
            new_img.save(output_path, 'WebP', quality=quality)
            size_kb = os.path.getsize(output_path) / 1024
            if size_kb <= MAX_SIZE_KB:
                return True

        return False
    except Exception as e:
        print(f"Error processing {input_path}: {e}")
        return False

def process_all_images():
    """Process all images in processed_images to 3:4 format"""
    print("\n" + "="*80)
    print("CREATING 3:4 ASPECT RATIO IMAGES (375x500px)")
    print("="*80 + "\n")

    # Create output directory if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    success_count = 0
    fail_count = 0

    for category in ['characters', 'categories']:
        src_folder = os.path.join(SOURCE_DIR, category)
        dst_folder = os.path.join(OUTPUT_DIR, category)

        if not os.path.exists(src_folder):
            continue

        os.makedirs(dst_folder, exist_ok=True)

        print(f"\n{category.upper()}:")

        for filename in sorted(os.listdir(src_folder)):
            if filename.lower().endswith('.webp'):
                src_path = os.path.join(src_folder, filename)
                dst_path = os.path.join(dst_folder, filename)

                if create_34_image(src_path, dst_path):
                    size_kb = os.path.getsize(dst_path) / 1024
                    print(f"  [OK] {filename} ({size_kb:.1f} KB)")
                    success_count += 1
                else:
                    print(f"  [FAIL] {filename}")
                    fail_count += 1

    print("\n" + "="*80)
    print(f"COMPLETE: {success_count} created, {fail_count} failed")
    print(f"Output folder: {OUTPUT_DIR}")
    print("="*80 + "\n")

if __name__ == "__main__":
    process_all_images()
