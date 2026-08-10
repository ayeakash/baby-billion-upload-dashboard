import json

# Already uploaded
uploaded = {
    'animals', 'around_us', 'geography', 'hindi_basics', 'math',
    'nature', 'our_world', 'science', 'stories',
    'about_india', 'birds', 'body_parts', 'english_speaking',
    'farm_animals', 'fractions', 'greater_and_lesser', 'knowledge',
    'prepositions', 'seasons', 'time', 'varnmala', 'vyanjan', 'words',
    'aladdin', 'clothes', 'hanuman', 'krishna', 'mishka_and_momo',
    'panchatantra', 'safety', 'shivji', 'sindbad', 'tenali', 'curious_kids'
}

with open('processed_images/image_matches.json', 'r') as f:
    matches = json.load(f)

print('UNMATCHED IMAGES:')
print('=' * 80)

unmatched = []
for img_type in ['playlists', 'categories', 'characters']:
    print(f'\n{img_type.upper()}:')
    count = 0
    for img_name, match_info in sorted(matches.get(img_type, {}).items()):
        if img_name.lower() in uploaded:
            continue

        display_name = match_info.get('display_name')
        if not display_name:
            unmatched.append(f'{img_type.rstrip("s")}: {img_name}')
            print(f'  - {img_name}')
            count += 1

    if count == 0:
        print('  (all matched or already uploaded)')

print('\n' + '=' * 80)
print(f'\nTotal unmatched images: {len(unmatched)}')
print('\nUnmatched list:')
for item in unmatched:
    print(f'  {item}')
