import json

# Load the matches
with open('processed_images/image_matches.json', 'r') as f:
    matches = json.load(f)

print("\n" + "="*80)
print("COMPLETE UPLOAD LIST - ALL ITEMS")
print("="*80)

# List playlists
print("\nPLAYLISTS TO UPLOAD (15 items):")
print("-" * 80)
playlist_count = 0
for img_name, match_info in sorted(matches.get('playlists', {}).items()):
    if match_info.get('display_name'):
        playlist_count += 1
        print(f"{playlist_count:2d}. {img_name:20} → {match_info['display_name']:30} ({match_info['score']:.0%})")

# List characters
print("\n\nCHARACTERS TO UPLOAD (19 items):")
print("-" * 80)
char_count = 0
for img_name, match_info in sorted(matches.get('characters', {}).items()):
    if match_info.get('display_name'):
        char_count += 1
        print(f"{char_count:2d}. {img_name:20} → {match_info['display_name']:30} ({match_info['score']:.0%})")

# List categories
print("\n\nCATEGORIES TO UPLOAD (60 items):")
print("-" * 80)
cat_count = 0
for img_name, match_info in sorted(matches.get('categories', {}).items()):
    if match_info.get('display_name'):
        cat_count += 1
        print(f"{cat_count:2d}. {img_name:25} → {match_info['display_name']:35} ({match_info['score']:.0%})")

# Summary
print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"Playlists:  {playlist_count:3d} items")
print(f"Characters: {char_count:3d} items")
print(f"Categories: {cat_count:3d} items")
print(f"TOTAL:      {playlist_count + char_count + cat_count:3d} items ready to upload")
print("="*80 + "\n")
