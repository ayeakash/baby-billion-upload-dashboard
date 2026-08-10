"""
CMS Image Matcher and Upload Assistant
- Matches processed images to CMS entries
- Handles typos and naming variations
- Provides guided upload instructions
- Generates upload checklist
"""

import os
import json
import re
from pathlib import Path
from difflib import SequenceMatcher

# Paths
PROCESSED_IMAGES_BASE = r"C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard\processed_images"
PLAYLISTS_DIR = os.path.join(PROCESSED_IMAGES_BASE, "playlists")
CHARACTERS_DIR = os.path.join(PROCESSED_IMAGES_BASE, "characters")
CATEGORIES_DIR = os.path.join(PROCESSED_IMAGES_BASE, "categories")

# CMS URLs
CMS_CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"
CMS_PLAYLISTS_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/playlists"

# CMS mappings extracted from playlists_categories.json (39 unique playlists)
PLAYLIST_NAMES = {
    'abc_learning': 'ABC Learning',
    'animals': 'Animals',
    'animals_and_nature': 'Animals & Nature',
    'around_us': 'Around Us',
    'bright_future': 'Bright Future',
    'calendar_and_time': 'Calendar & Time',
    'colors_and_shapes': 'Colors & Shapes',
    'curious_kids': 'Curious Kids',
    'direct_from_classroom': 'Direct From Classroom',
    'english_basics': 'English Basics',
    'english_fluency': 'English Fluency',
    'environment': 'Environment',
    'family_and_people': 'Family & People',
    'food': 'Food',
    'food_and_healthy_eating': 'Food & Healthy Eating',
    'future_scientist': 'Future Scientist',
    'geography': 'Geography',
    'good_habits': 'Good Habits',
    'hindi': 'Hindi',
    'hindi_basics': 'Hindi Basics',
    'kids_favorites': 'Kids\' Favorites',
    'learn_and_explore': 'Learn & Explore',
    'little_heroes': 'Little Heroes',
    'maths': 'Maths',
    'me_and_my_family': 'Me & My Family',
    'my_body_and_clean_habits': 'My Body & Clean Habits',
    'nature': 'Nature',
    'new_on_babybillion': 'New On BabyBillion',
    'numbers_and_easy_math': 'Numbers & Easy Math',
    'our_world': 'Our World',
    'ready_for_school': 'Ready for School',
    'rhymes_and_music': 'Rhymes & Music',
    'science': 'Science',
    'space_adventures': 'Space Adventures',
    'stories': 'Stories',
    'talk_and_manners': 'Talk & Manners',
    'things_and_objects': 'Things & Objects',
    'top_10_in_india': 'Top 10 in India',
    'vehicles_and_safety': 'Vehicles and Safety',
    # Explicit mappings for unmatched images
    'alphabets': 'ABC Learning',
    'english': 'English Basics',
    'manners': 'Talk & Manners',
    'numbers': 'Numbers & Easy Math',
    'rhymes': 'Rhymes & Music',
}

CHARACTER_NAMES = {
    'alladin': 'Alladin',
    'arjun': 'Arjun',
    'golu': 'Golu',
    'guddi': 'Guddi',
    'hanuman': 'Hanuman',
    'jay': 'Jay',
    'krishna': 'Krishna',
    'meera': 'Meera',
    'mia': 'Mia',
    'mishka': 'Mishka',
    'priya': 'Priya',
    'ria': 'Ria',
    'shivji': 'Shivji',
    'sindbad': 'Sindbad',
    'tara': 'Tara',
    'teja': 'Teja',
    'tenali': 'Tenali',
    'veer': 'Veer',
    'zoya': 'Zoya',
}

CATEGORY_NAMES = {
    '100_200': '100-200',
    '1_100': '1-100',
    '3d_shapes': '3D Shapes',
    'abc_learning': 'ABC Learning',
    'about_india': 'About India',
    'add_with_fun': 'Add With Fun',
    'akbar_and_birbal': 'Akbar And Birbal',
    'aladdin': 'Aladdin',
    'animals_and_nature': 'Animals & Nature',
    'arjun': 'Arjun',
    'baby_animals': 'Baby Animals',
    'before_and_after_numbers': 'Before & After Numbers',
    'calendar_and_time': 'Calendar & Time',
    'celebrate_with_everyone': 'Celebrate With Everyone',
    'choose_healthy_foods': 'Choose Healthy Foods',
    'clothes': 'Clothes',
    'colors_and_shapes': 'Colors & Shapes',
    'count_in_hindi': 'Count in Hindi',
    'count_with_confidence': 'Count With Confidence',
    'counting': 'Counting',
    'dinosaur': 'Dinosaur',
    'division': 'Division',
    'english_stories': 'English Stories',
    'environment': 'Environment',
    'explore_different_sports': 'Explore Different Sports',
    'explore_nature_around': 'Explore Nature Around',
    'family_and_people': 'Family & People',
    'find_favorite_toys': 'Find Favorite Toys',
    'find_things_around': 'Find Things Around',
    'food_and_healthy_eating': 'Food & Healthy eating',
    'fractions': 'Fractions',
    'greater_and_lesser': 'Greater & Lesser',
    'guddi': 'Guddi',
    'hanuman': 'Hanuman',
    'hindi_stories': 'Hindi Stories',
    'jai': 'Jai',
    'jungle_animals': 'Jungle Animals',
    'know_body_parts': 'Know Body Parts',
    'knowledge': 'Knowledge',
    'krishna': 'Krishna',
    'learn_color_names': 'Learn Color names',
    'learn_new_words': 'Learn New Words',
    'learn_opposite_words': 'Learn Opposite Words',
    'learn_your_abc': 'Learn Your ABC',
    'lets_go_outside': 'Let\'s Go Outside',
    'listen_to_poems': 'Listen to Poems',
    'maths': 'Maths',
    'maths_with_ms_pranika': 'Maths With Ms Pranika',
    'meet_cute_animals': 'Meet Cute Animals',
    'meet_farm_animals': 'Meet Farm Animals',
    'meet_ocean_animals': 'Meet Ocean Animals',
    'meet_tiny_insects': 'Meet Tiny Insects',
    'meet_your_family': 'Meet Your Family',
    'mia': 'Mia',
    'mishka_and_momo': 'Mishka And Momo',
    'money': 'Money',
    'multiplication': 'Multiplication',
    'my_body_and_clean_habits': 'My Body & Clean Habits',
    'name_your_fruits': 'Name Your Fruits',
    'name_your_veggies': 'Name Your Veggies',
    'new_words': 'New Words',
    'numbers_and_easy_math': 'Numbers & Easy Math',
    'odd_and_even': 'Odd & Even',
    'panchatantra': 'Panchatantra',
    'paryayvachi_shabd': 'Paryayvachi Shabd',
    'place_your_numbers': 'Place Your Numbers',
    'play_with_patterns': 'Play With Patterns',
    'practice_good_habits': 'Practice Good Habits',
    'prepositions': 'Prepositions',
    'priya': 'Priya',
    'pronounce_with_ms_nidhi': 'Pronounce With Ms Nidhi',
    'read_simple_words': 'Read Simple Words',
    'riya': 'Riya',
    'safety': 'Safety',
    'science_made_fun': 'Science Made Fun',
    'shapes_with_ms_isha': 'Shapes With Ms Isha',
    'shivji': 'Shivji',
    'sindbad': 'Sindbad',
    'sing_along_rhymes': 'Sing Along Rhymes',
    'songs': 'Songs',
    'sounds_and_words': 'Sounds & Words',
    'speak_it_right': 'Speak It Right',
    'speak_simple_hindi': 'Speak Simple Hindi',
    'speak_with_confidence': 'Speak With Confidence',
    'spot_colorful_birds': 'Spot Colorful Birds',
    'spot_different_shapes': 'Spot Different Shapes',
    'spot_moving_vehicles': 'Spot Moving Vehicles',
    'start_with_sentences': 'Start With Sentences',
    'stay_safe_everyday': 'Stay Safe Everyday',
    'subtract_with_fun': 'Subtract With Fun',
    'talk_and_manners': 'Talk & Manners',
    'tara': 'Tara',
    'teja': 'Teja',
    'tenali': 'Tenali',
    'things_and_objects': 'Things & Objects',
    'time': 'Time',
    'try_these_actions': 'Try These Actions',
    'understand_your_feelings': 'Understand Your Feelings',
    'varnmala': 'Varnmala',
    'veer': 'Veer',
    'vehicles_and_safety': 'Vehicles and Safety',
    'vilom_shabd': 'Vilom Shabd',
    'visit_new_countries': 'Visit New Countries',
    'visit_outer_space': 'Visit Outer Space',
    'watch_plants_grow': 'Watch Plants Grow',
    'what_do_they_do': 'What Do They Do',
    'why_seasons_change': 'Why Seasons Change',
    'write_your_alphabets': 'Write Your Alphabets',
    'write_your_numbers': 'Write Your Numbers',
    'zoya': 'Zoya',
    # Explicit mappings for unmatched images
    'ABC': 'Learn Your ABC',
    'action_words': 'Try These Actions',
    'colors': 'Learn Color names',
    'community_helpers': 'What Do They Do',
    'countries': 'Visit New Countries',
    'emotions': 'Understand Your Feelings',
    'english': 'Learn New Words',
    'festivals': 'Celebrate With Everyone',
    'food_items': 'Choose Healthy Foods',
    'fruits': 'Name Your Fruits',
    'good_habits': 'Practice Good Habits',
    'home_items': 'Find Things Around',
    'ms_isha': 'Shapes With Ms Isha',
    'ms_nidhi': 'Pronounce With Ms Nidhi',
    'ms_pranika': 'Maths With Ms Pranika',
    'my_body': 'Know Body Parts',
    'my_family': 'Meet Your Family',
    'opposites': 'Learn Opposite Words',
    'places_to_go': 'Let\'s Go Outside',
    'plants': 'Watch Plants Grow',
    'professions': 'What Do They Do',
    'sight_words': 'Read Simple Words',
    'simple_sentences': 'Start With Sentences',
    'space': 'Visit Outer Space',
    'sports': 'Explore Different Sports',
    'technology': 'Knowledge',
    'toys': 'Find Favorite Toys',
    'vegetables': 'Name Your Veggies',
    'vehicles': 'Spot Moving Vehicles',
    'wild_animals': 'Jungle Animals',
}


def normalize_name(name):
    """Normalize a name for comparison"""
    return re.sub(r'[_\s-]+', ' ', name.lower().strip())


def similarity_ratio(a, b):
    """Calculate similarity between two strings (0-1)"""
    return SequenceMatcher(None, a, b).ratio()


def find_best_match(search_name, candidates_dict, threshold=0.75):
    """
    Find best matching candidate from a dict
    Returns (key, display_name, score)
    """
    search_norm = normalize_name(search_name)

    best_key = None
    best_name = None
    best_score = 0

    for key, display_name in candidates_dict.items():
        candidate_norm = normalize_name(key)
        score = similarity_ratio(search_norm, candidate_norm)

        if score > best_score:
            best_score = score
            best_key = key
            best_name = display_name

    if best_score >= threshold:
        return best_key, best_name, best_score

    # Try matching against display names too
    for key, display_name in candidates_dict.items():
        display_norm = normalize_name(display_name)
        score = similarity_ratio(search_norm, display_norm)

        if score > best_score:
            best_score = score
            best_key = key
            best_name = display_name

    if best_score >= threshold:
        return best_key, best_name, best_score

    return None, None, best_score


def get_image_files(directory):
    """Get all image files from a directory"""
    if not os.path.exists(directory):
        return {}

    images = {}
    for filename in os.listdir(directory):
        if filename.lower().endswith(('.webp', '.jpg', '.jpeg', '.png')):
            name = os.path.splitext(filename)[0]
            images[name] = os.path.join(directory, filename)

    return images


def generate_matching_report():
    """Generate a matching report for all images"""
    print("\n" + "="*80)
    print("CMS IMAGE MATCHER REPORT")
    print("="*80)

    # Get all images
    playlist_images = get_image_files(PLAYLISTS_DIR)
    character_images = get_image_files(CHARACTERS_DIR)
    category_images = get_image_files(CATEGORIES_DIR)

    print("\n" + "="*80)
    print("PLAYLIST MAPPINGS (1:1 Ratio)")
    print("="*80)
    print(f"{'Image Name':<30} {'CMS Name':<30} {'Match Score':<15} {'Status'}")
    print("-"*80)

    playlist_matches = {}
    for img_name in sorted(playlist_images.keys()):
        key, display_name, score = find_best_match(img_name, PLAYLIST_NAMES)
        playlist_matches[img_name] = {
            'key': key,
            'display_name': display_name,
            'score': score,
            'path': playlist_images[img_name]
        }

        status = "[MATCH]" if score >= 0.9 else "[FUZZY]" if score >= 0.75 else "[NOMATCH]"
        match_display = display_name if display_name else "—"
        print(f"{img_name:<30} {match_display:<30} {score:>6.1%}         {status}")

    print("\n" + "="*80)
    print("CHARACTER MAPPINGS (3:4 Ratio)")
    print("="*80)
    print(f"{'Image Name':<30} {'CMS Name':<30} {'Match Score':<15} {'Status'}")
    print("-"*80)

    character_matches = {}
    for img_name in sorted(character_images.keys()):
        key, display_name, score = find_best_match(img_name, CHARACTER_NAMES)
        character_matches[img_name] = {
            'key': key,
            'display_name': display_name,
            'score': score,
            'path': character_images[img_name]
        }

        status = "[MATCH]" if score >= 0.9 else "[FUZZY]" if score >= 0.75 else "[NOMATCH]"
        match_display = display_name if display_name else "—"
        print(f"{img_name:<30} {match_display:<30} {score:>6.1%}         {status}")

    print("\n" + "="*80)
    print("CATEGORY MAPPINGS (3:4 Ratio)")
    print("="*80)
    print(f"{'Image Name':<30} {'CMS Name':<30} {'Match Score':<15} {'Status'}")
    print("-"*80)

    category_matches = {}
    for img_name in sorted(category_images.keys()):
        key, display_name, score = find_best_match(img_name, CATEGORY_NAMES)
        category_matches[img_name] = {
            'key': key,
            'display_name': display_name,
            'score': score,
            'path': category_images[img_name]
        }

        status = "[MATCH]" if score >= 0.9 else "[FUZZY]" if score >= 0.75 else "[NOMATCH]"
        match_display = display_name if display_name else "—"
        print(f"{img_name:<30} {match_display:<30} {score:>6.1%}         {status}")

    return playlist_matches, character_matches, category_matches


def generate_upload_checklist(playlist_matches, character_matches, category_matches):
    """Generate upload checklist and instructions"""

    checklist_path = os.path.join(PROCESSED_IMAGES_BASE, "UPLOAD_CHECKLIST.txt")

    with open(checklist_path, 'w') as f:
        f.write("="*80 + "\n")
        f.write("IMAGE UPLOAD CHECKLIST FOR BABY BILLION CMS\n")
        f.write("="*80 + "\n\n")

        f.write("INSTRUCTIONS:\n")
        f.write("-"*80 + "\n")
        f.write("1. Go to: " + CMS_PLAYLISTS_URL + "\n")
        f.write("2. Click 'Edit' on each playlist\n")
        f.write("3. Upload the image to BOTH thumbnail fields\n")
        f.write("4. Save changes\n")
        f.write("5. Repeat for categories\n\n")

        f.write("="*80 + "\n")
        f.write("PLAYLISTS TO UPLOAD\n")
        f.write("="*80 + "\n\n")

        for img_name, match_info in sorted(playlist_matches.items()):
            if match_info['display_name']:
                f.write(f"Playlist: {match_info['display_name']}\n")
                f.write(f"Image File: {img_name}.png\n")
                f.write(f"Path: {match_info['path']}\n")
                f.write(f"Match Quality: {match_info['score']:.0%}\n")
                f.write(f"[ ] Upload to: {CMS_PLAYLISTS_URL}\n")
                f.write("\n")
            else:
                f.write(f"[WARN] {img_name} - NO MATCH FOUND\n\n")

        f.write("="*80 + "\n")
        f.write("CHARACTERS TO UPLOAD\n")
        f.write("="*80 + "\n\n")

        for img_name, match_info in sorted(character_matches.items()):
            if match_info['display_name']:
                f.write(f"Character: {match_info['display_name']}\n")
                f.write(f"Image File: {img_name}.png\n")
                f.write(f"Path: {match_info['path']}\n")
                f.write(f"Match Quality: {match_info['score']:.0%}\n")
                f.write(f"[ ] Upload to: {CMS_PLAYLISTS_URL} (if character is in playlist)\n")
                f.write("\n")
            else:
                f.write(f"[WARN] {img_name} - NO MATCH FOUND\n\n")

        f.write("="*80 + "\n")
        f.write("CATEGORIES TO UPLOAD\n")
        f.write("="*80 + "\n\n")

        for img_name, match_info in sorted(category_matches.items()):
            if match_info['display_name']:
                f.write(f"Category: {match_info['display_name']}\n")
                f.write(f"Image File: {img_name}.png\n")
                f.write(f"Path: {match_info['path']}\n")
                f.write(f"Match Quality: {match_info['score']:.0%}\n")
                f.write(f"[ ] Upload to: {CMS_CATEGORIES_URL}\n")
                f.write("\n")
            else:
                f.write(f"[WARN] {img_name} - NO MATCH FOUND\n\n")

        f.write("="*80 + "\n")
        f.write("SUMMARY\n")
        f.write("="*80 + "\n")

        playlist_count = sum(1 for m in playlist_matches.values() if m['display_name'])
        character_count = sum(1 for m in character_matches.values() if m['display_name'])
        category_count = sum(1 for m in category_matches.values() if m['display_name'])
        total_matched = playlist_count + character_count + category_count

        f.write(f"Playlists to upload: {playlist_count}\n")
        f.write(f"Characters to upload: {character_count}\n")
        f.write(f"Categories to upload: {category_count}\n")
        f.write(f"Total matched: {total_matched}\n\n")

        unmatched = sum(1 for m in playlist_matches.values() if not m['display_name'])
        unmatched += sum(1 for m in character_matches.values() if not m['display_name'])
        unmatched += sum(1 for m in category_matches.values() if not m['display_name'])

        if unmatched > 0:
            f.write(f"[WARN] WARNING: {unmatched} images could not be matched automatically!\n")
            f.write("Review the unmatched images above and upload manually or update the mapping.\n")

    print(f"\n[OK] Checklist saved to: {checklist_path}")


def save_matches_json(playlist_matches, character_matches, category_matches):
    """Save matches to JSON for programmatic use"""
    json_path = os.path.join(PROCESSED_IMAGES_BASE, "image_matches.json")

    matches_data = {
        'playlists': {k: v for k, v in playlist_matches.items()},
        'characters': {k: v for k, v in character_matches.items()},
        'categories': {k: v for k, v in category_matches.items()},
    }

    # Remove path objects for JSON serialization
    for category in ['playlists', 'characters', 'categories']:
        for name in matches_data[category]:
            if 'path' in matches_data[category][name]:
                del matches_data[category][name]['path']

    with open(json_path, 'w') as f:
        json.dump(matches_data, f, indent=2)

    print(f"[OK] Matches saved to: {json_path}")


def main():
    """Main function"""
    print("\n" + "="*80)
    print("BABY BILLION CMS IMAGE MATCHER")
    print("="*80)

    # Generate matching report
    playlist_matches, character_matches, category_matches = generate_matching_report()

    # Generate checklist
    generate_upload_checklist(playlist_matches, character_matches, category_matches)

    # Save JSON
    save_matches_json(playlist_matches, character_matches, category_matches)

    print("\n" + "="*80)
    print("[OK] MATCHING COMPLETE")
    print("="*80)
    print("\nNext steps:")
    print(f"1. Review the checklist: {os.path.join(PROCESSED_IMAGES_BASE, 'UPLOAD_CHECKLIST.txt')}")
    print(f"2. Go to CMS URLs and upload images to matched entries")
    print(f"3. Upload same image to BOTH thumbnail fields for each entry")


if __name__ == "__main__":
    main()
