import json

with open('processed_images/image_matches.json', 'r') as f:
    matches = json.load(f)

# Create table
print("\n" + "="*120)
print("CATEGORY IMAGE TO CMS MAPPING TABLE")
print("="*120 + "\n")

print(f"{'#':<4} {'Image Filename':<25} {'CMS Category Name':<45} {'Match Score':<15} {'Status':<10}")
print("-"*120)

matched = 0
unmatched = 0

for idx, (img_name, match_info) in enumerate(sorted(matches.get('categories', {}).items()), 1):
    display = match_info.get('display_name')
    score = match_info.get('score', 0)

    if display:
        status = "✓ MATCH" if score >= 0.90 else "~ FUZZY"
        matched += 1
    else:
        display = "NO MATCH"
        status = "✗ NO"
        unmatched += 1

    print(f"{idx:<4} {img_name:<25} {display:<45} {score:>6.0%}        {status:<10}")

print("-"*120)
print(f"\nTotal Categories: {matched + unmatched}")
print(f"  ✓ With Matches: {matched}")
print(f"  ✗ No Matches:   {unmatched}")
print("="*120 + "\n")

# Save to CSV format
with open('processed_images/CATEGORY_MAPPING.csv', 'w') as f:
    f.write("Image Filename,CMS Category Name,Match Score,Status\n")
    for img_name, match_info in sorted(matches.get('categories', {}).items()):
        display = match_info.get('display_name') or 'NO MATCH'
        score = match_info.get('score', 0)
        status = 'MATCH' if display != 'NO MATCH' else 'NO MATCH'
        f.write(f'"{img_name}","{display}",{score:.0%},{status}\n')

print("CSV file saved to: processed_images/CATEGORY_MAPPING.csv")
