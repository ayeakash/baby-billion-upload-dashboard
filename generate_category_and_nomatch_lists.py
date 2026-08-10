import json
import os

# Load the matches
with open('processed_images/image_matches.json', 'r') as f:
    matches = json.load(f)

# Get all category image files
categories_dir = 'processed_images/categories'
all_category_files = set()
for filename in os.listdir(categories_dir):
    if filename.endswith('.webp'):
        name = filename.replace('.webp', '')
        all_category_files.add(name)

print("\n" + "="*80)
print("ALL UPDATED CATEGORIES (with 1:1 ratio)")
print("="*80 + "\n")

matched_categories = {}
unmatched_images = []

for img_name, match_info in sorted(matches.get('categories', {}).items()):
    if match_info.get('display_name'):
        matched_categories[img_name] = match_info['display_name']

# Print matched categories with numbers
print("CATEGORIES WITH MATCHES (49):")
print("-" * 80)
for idx, (img_name, display_name) in enumerate(sorted(matched_categories.items()), 1):
    print(f"{idx:2d}. {display_name:40} (file: {img_name})")

# Find unmatched images
print("\n\nIMAGE FILES WITHOUT MATCHES:")
print("-" * 80)
unmatched_count = 0
for img_name in sorted(all_category_files):
    if img_name not in matched_categories:
        unmatched_count += 1
        print(f"{unmatched_count:2d}. {img_name}")

print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"Total category images processed: {len(all_category_files)}")
print(f"Categories with matches:         {len(matched_categories)}")
print(f"Images without matches:          {unmatched_count}")
print("="*80 + "\n")

# Save to file for reference
with open('processed_images/CATEGORIES_SUMMARY.txt', 'w') as f:
    f.write("="*80 + "\n")
    f.write("ALL UPDATED CATEGORIES (with 1:1 ratio)\n")
    f.write("="*80 + "\n\n")

    f.write("CATEGORIES WITH MATCHES (49):\n")
    f.write("-" * 80 + "\n")
    for idx, (img_name, display_name) in enumerate(sorted(matched_categories.items()), 1):
        f.write(f"{idx:2d}. {display_name:40} (file: {img_name})\n")

    f.write("\n\nIMAGE FILES WITHOUT MATCHES:\n")
    f.write("-" * 80 + "\n")
    for idx, img_name in enumerate(sorted(all_category_files), 1):
        if img_name not in matched_categories:
            f.write(f"{idx:2d}. {img_name}\n")

    f.write("\n" + "="*80 + "\n")
    f.write("SUMMARY\n")
    f.write("="*80 + "\n")
    f.write(f"Total category images processed: {len(all_category_files)}\n")
    f.write(f"Categories with matches:         {len(matched_categories)}\n")
    f.write(f"Images without matches:          {unmatched_count}\n")
    f.write("="*80 + "\n")

print("Summary saved to: processed_images/CATEGORIES_SUMMARY.txt")
