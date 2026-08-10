import json

with open('processed_images/image_matches.json', 'r') as f:
    matches = json.load(f)

print("\n" + "="*100)
print("COMPLETE IMAGE TO CMS MAPPING")
print("="*100 + "\n")

print("PLAYLISTS MAPPING:")
print("-"*100)
print(f"{'Image Filename':<30} {'CMS Playlist Name':<40} {'Match %':<15}")
print("-"*100)
for img_name, match_info in sorted(matches.get('playlists', {}).items()):
    display = match_info.get('display_name') or 'NO MATCH'
    score = match_info.get('score', 0)
    print(f"{img_name:<30} {display:<40} {score:>6.0%}")

print("\n\nCHARACTERS MAPPING:")
print("-"*100)
print(f"{'Image Filename':<30} {'CMS Character Name':<40} {'Match %':<15}")
print("-"*100)
for img_name, match_info in sorted(matches.get('characters', {}).items()):
    display = match_info.get('display_name') or 'NO MATCH'
    score = match_info.get('score', 0)
    print(f"{img_name:<30} {display:<40} {score:>6.0%}")

print("\n\nCATEGORIES MAPPING:")
print("-"*100)
print(f"{'Image Filename':<30} {'CMS Category Name':<40} {'Match %':<15}")
print("-"*100)
for img_name, match_info in sorted(matches.get('categories', {}).items()):
    display = match_info.get('display_name') or 'NO MATCH'
    score = match_info.get('score', 0)
    print(f"{img_name:<30} {display:<40} {score:>6.0%}")

print("\n" + "="*100)
print("SUMMARY")
print("="*100)

playlists = {k: v for k, v in matches.get('playlists', {}).items() if v.get('display_name')}
characters = {k: v for k, v in matches.get('characters', {}).items() if v.get('display_name')}
categories = {k: v for k, v in matches.get('categories', {}).items() if v.get('display_name')}

print(f"\nPlaylists mapped:  {len(playlists)}")
print(f"Characters mapped: {len(characters)}")
print(f"Categories mapped: {len(categories)}")
print(f"TOTAL MAPPED:      {len(playlists) + len(characters) + len(categories)}")
print("="*100 + "\n")

# Save to text file
with open('processed_images/MAPPING_REPORT.txt', 'w') as f:
    f.write("\n" + "="*100 + "\n")
    f.write("COMPLETE IMAGE TO CMS MAPPING\n")
    f.write("="*100 + "\n\n")

    f.write("PLAYLISTS MAPPING:\n")
    f.write("-"*100 + "\n")
    f.write(f"{'Image Filename':<30} {'CMS Playlist Name':<40} {'Match %':<15}\n")
    f.write("-"*100 + "\n")
    for img_name, match_info in sorted(matches.get('playlists', {}).items()):
        display = match_info.get('display_name', 'NO MATCH')
        score = match_info.get('score', 0)
        f.write(f"{img_name:<30} {display:<40} {score:>6.0%}\n")

    f.write("\n\nCHARACTERS MAPPING:\n")
    f.write("-"*100 + "\n")
    f.write(f"{'Image Filename':<30} {'CMS Character Name':<40} {'Match %':<15}\n")
    f.write("-"*100 + "\n")
    for img_name, match_info in sorted(matches.get('characters', {}).items()):
        display = match_info.get('display_name', 'NO MATCH')
        score = match_info.get('score', 0)
        f.write(f"{img_name:<30} {display:<40} {score:>6.0%}\n")

    f.write("\n\nCATEGORIES MAPPING:\n")
    f.write("-"*100 + "\n")
    f.write(f"{'Image Filename':<30} {'CMS Category Name':<40} {'Match %':<15}\n")
    f.write("-"*100 + "\n")
    for img_name, match_info in sorted(matches.get('categories', {}).items()):
        display = match_info.get('display_name', 'NO MATCH')
        score = match_info.get('score', 0)
        f.write(f"{img_name:<30} {display:<40} {score:>6.0%}\n")

    f.write("\n" + "="*100 + "\n")
    f.write("SUMMARY\n")
    f.write("="*100 + "\n")
    f.write(f"\nPlaylists mapped:  {len(playlists)}\n")
    f.write(f"Characters mapped: {len(characters)}\n")
    f.write(f"Categories mapped: {len(categories)}\n")
    f.write(f"TOTAL MAPPED:      {len(playlists) + len(characters) + len(categories)}\n")
    f.write("="*100 + "\n")

print("Report saved to: processed_images/MAPPING_REPORT.txt")
