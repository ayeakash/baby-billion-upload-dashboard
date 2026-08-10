import json
from difflib import SequenceMatcher

# Load the actual CMS structure
with open(r'C:\Users\Aashitha\Downloads\playlists_categories.json', 'r') as f:
    cms_data = json.load(f)

# Unmatched images from our processed set
unmatched = {
    'playlists': ['alphabets', 'english', 'manners', 'numbers', 'rhymes'],
    'categories': [
        'ABC', 'action_words', 'colors', 'community_helpers', 'countries',
        'emotions', 'english', 'festivals', 'food_items', 'fruits',
        'good_habits', 'home_items', 'ms_isha', 'ms_nidhi', 'ms_pranika',
        'my_body', 'my_family', 'opposites', 'places_to_go', 'plants',
        'professions', 'sight_words', 'simple_sentences', 'space', 'sports',
        'technology', 'toys', 'vegetables', 'vehicles', 'wild_animals'
    ]
}

def normalize(s):
    return s.lower().replace('_', ' ').replace('&', 'and')

def similarity(a, b):
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()

print("FINDING MATCHES FROM CMS JSON")
print("=" * 80)

# Extract all playlist names from JSON
cms_playlists = set()
for item in cms_data:
    cms_playlists.add(item['playlist_name'])

# Extract all category names from JSON
cms_categories = set()
for item in cms_data:
    for cat in item['categories']:
        cms_categories.add(cat['category_name'])

print("\nPLAYLIST MATCHES:")
print("-" * 80)
for unmatched_name in unmatched['playlists']:
    best_match = None
    best_score = 0
    for cms_name in cms_playlists:
        score = similarity(unmatched_name, cms_name)
        if score > best_score:
            best_score = score
            best_match = cms_name

    print(f"{unmatched_name:20} -> {best_match:30} ({best_score:.1%})")

print("\n\nCATEGORY MATCHES:")
print("-" * 80)
for unmatched_name in unmatched['categories']:
    best_match = None
    best_score = 0
    for cms_name in cms_categories:
        score = similarity(unmatched_name, cms_name)
        if score > best_score:
            best_score = score
            best_match = cms_name

    if best_score > 0.5:  # Only show matches above 50% similarity
        print(f"{unmatched_name:25} -> {best_match:35} ({best_score:.1%})")
    else:
        print(f"{unmatched_name:25} -> NO GOOD MATCH (best: {best_match} {best_score:.1%})")

print("\n" + "=" * 80)
print(f"Total unmatched: {len(unmatched['playlists']) + len(unmatched['categories'])}")
