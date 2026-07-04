"""
auto_map.py — Auto-generate playlist → Notion category mapping
by fuzzy-matching playlist names to category names.
"""
import csv, os, json, re, unicodedata
from difflib import SequenceMatcher

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLAYLIST_CSV = os.path.join(SCRIPT_DIR, "Copy of Playlists Language Tagging - Playlist_new (1).csv")
NOTION_CSV = os.path.join(SCRIPT_DIR, "notion.csv")

def normalize(s):
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s

# Load Notion categories with counts
categories = {}
with open(NOTION_CSV, "r", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        cat = (row.get("Category") or "").strip()
        if cat:
            categories[cat] = categories.get(cat, 0) + 1

# Load playlists
playlists = []
with open(PLAYLIST_CSV, "r", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        playlists.append({
            "id": row["playlist_id"],
            "title": row["title"],
            "age_groups": row.get("age_groups", ""),
            "language": row.get("Language", ""),
        })

# Manual mappings for known ambiguous ones and keyword-based matching
KEYWORD_MAP = {
    # Playlist keyword → Notion categories
    "abc": ["ABC"],
    "learn your abc": ["ABC"],
    "abc learning": ["ABC"],
    "safety": ["Safety", "Home Safety, Safety"],
    "stay safe": ["Safety", "Home Safety, Safety"],
    "body parts": ["My Body"],
    "know body parts": ["My Body"],
    "my body": ["My Body", "My Body, Physical Movement", "My Body, Science"],
    "clean habits": ["Good habits", "My Body"],
    "colors": ["Colors"],
    "learn color": ["Colors"],
    "shapes": ["shapes", "3D  Shapes", "3D  Shapes, shapes"],
    "3d shapes": ["3D  Shapes", "3D  Shapes, shapes"],
    "spot different shapes": ["shapes", "3D  Shapes"],
    "colors & shapes": ["Colors", "shapes"],
    "vehicles": ["Vehicles"],
    "spot moving vehicles": ["Vehicles"],
    "vehicles and safety": ["Vehicles"],
    "fruits": ["Fruits"],
    "name your fruits": ["Fruits"],
    "veggies": ["Vegetables"],
    "name your veggies": ["Vegetables"],
    "animals": ["Animals", "Animals, Wild Animals"],
    "meet cute animals": ["Animals"],
    "jungle animals": ["Animals, Wild Animals"],
    "farm animals": ["Animals, Farm Animals", "Farm Animals"],
    "meet farm animals": ["Animals, Farm Animals", "Farm Animals"],
    "baby animals": ["Animals, Baby Animals"],
    "ocean animals": ["Sea Animals", "Animals, Sea Animals"],
    "meet ocean animals": ["Sea Animals", "Animals, Sea Animals"],
    "sea animals": ["Sea Animals", "Animals, Sea Animals"],
    "good habits": ["Good habits"],
    "practice good habits": ["Good habits"],
    "science": ["Science", "Science, Space", "Science, Weather", "Science, Time", "Plants, Science", "My Body, Science"],
    "science made fun": ["Science"],
    "sports": ["Sports"],
    "explore different sports": ["Sports"],
    "stories": ["Stories", "Classic Stories"],
    "english stories": ["Stories", "Classic Stories", "Sindbad", "Tenali", "Alladin", "Panchatantra", "Vikram Betal", "Krishna, Stories"],
    "hindi stories": ["Stories", "Classic Stories", "Sindbad", "Tenali", "Alladin", "Panchatantra", "Vikram Betal", "Krishna, Stories"],
    "multiplication": ["Multiplication"],
    "subtraction": ["Subtraction"],
    "subtract with fun": ["Subtraction"],
    "division": ["Division"],
    "fractions": ["Fractions"],
    "money": ["Money"],
    "about india": ["About India"],
    "clothes": ["Cloths"],
    "emotions": ["Emotions"],
    "how are you": ["Emotions", "English speaking"],
    "counting": ["Counting"],
    "count with confidence": ["Counting"],
    "count in hindi": ["Hindi  Counting"],
    "1-100": ["1-100, Counting", "Counting"],
    "100-200": ["Counting"],
    "phonics": ["Phonics"],
    "sounds & words": ["Phonics", "CVC Words"],
    "community helpers": ["Community Helpers"],
    "what do they do": ["Community Helpers", "Professions"],
    "food": ["Food items"],
    "food & healthy eating": ["Food items"],
    "choose healthy foods": ["Food items"],
    "home items": ["Home Items"],
    "find things around": ["Home Items"],
    "things & objects": ["Home Items"],
    "family": ["My Family", "Relationships"],
    "family & people": ["My Family", "Relationships"],
    "meet your family": ["My Family"],
    "birds": ["Birds", "Animals, Birds, Wild Animals"],
    "spot colorful birds": ["Birds"],
    "insects": ["Insects"],
    "meet tiny insects": ["Insects"],
    "nature": ["Nature"],
    "explore nature around": ["Nature"],
    "plants": ["Plants", "Plants, Science"],
    "watch plants grow": ["Plants"],
    "weather": ["Weather", "Science, Weather"],
    "seasons": ["Seasons"],
    "why seasons change": ["Seasons", "Weather"],
    "places": ["Places  We Go"],
    "let's go outside": ["Places  We Go"],
    "geography": ["Countries", "About India"],
    "cities": ["Countries"],
    "festivals": ["Festivals"],
    "celebrate with everyone": ["Festivals"],
    "technology": ["Technology"],
    "toys": ["Toys"],
    "find favorite toys": ["Toys"],
    "time": ["Time", "Science, Time"],
    "calendar & time": ["Time"],
    "opposites": ["Opposites"],
    "learn opposite words": ["Opposites"],
    "prepositions": ["Prepositions"],
    "addition": ["Addition"],
    "add with fun": ["Addition"],
    "place your numbers": ["Number  Ordering", "Greater  Lesser"],
    "before & after numbers": ["Number  Ordering"],
    "numbers & easy math": ["Number  Ordering", "Greater  Lesser"],
    "odd & even": ["Number  Ordering"],
    "patterns": ["Patterns"],
    "play with patterns": ["Patterns"],
    "musical instruments": ["Musical instruments"],
    "music instruments": ["Musical instruments"],
    "english speaking": ["English speaking", "English speaking, Simple  sentences"],
    "speak with confidence": ["English speaking", "English speaking, Simple  sentences"],
    "speak it right": ["English speaking"],
    "talk & manners": ["English speaking", "Simple  sentences"],
    "start with sentences": ["Simple  sentences", "English speaking, Simple  sentences"],
    "simple sentences": ["Simple  sentences"],
    "words": ["Words", "Sight  words", "CVC Words"],
    "learn new words": ["Words", "Sight  words", "CVC Words", "Action words", "Action words, Words"],
    "new words": ["Words", "Sight  words", "CVC Words"],
    "read simple words": ["Sight  words", "CVC Words", "Words"],
    "sight words": ["Sight  words"],
    "action words": ["Action words", "Action words, My Body", "Action words, Words", "Action words, Physical Movement"],
    "try these actions": ["Action words", "Action words, My Body", "Action words, Physical Movement"],
    "vyanjan": ["Varnamala, Vyanjan", "Vyanjan"],
    "varnmala": ["Varnamala, Vyanjan", "Varnamala", "Swar, Varnamala"],
    "swar": ["Swar", "Swar, Varnamala"],
    "vilom shabd": ["Vilom Shabd"],
    "paryayvachi shabd": ["Paryayavachi Shabd"],
    "hindi basics": ["Hindi Basics"],
    "speak simple hindi": ["Hindi Basics"],
    "poems": ["Hindi Poems"],
    "listen to poems": ["Hindi Poems"],
    "sing along rhymes": ["Hindi Poems"],
    "dinosaur": ["Animals"],  # no exact match
    "space": ["Science, Space"],
    "visit outer space": ["Science, Space"],
    "funny animal sounds": ["Animals"],
    "animals & nature": ["Animals", "Nature"],
    "tracing": ["TracingABC", "Tracing123"],
    "maths": ["Addition", "Subtraction", "Multiplication", "Division", "Fractions"],
    "entertainment": ["Stories", "Classic Stories"],
    "knowledge": ["Science", "About India", "Countries"],
    "miscellaneous": [],
    "art & craft": [],
    "environment": ["Nature", "Plants"],
    "songs": [],
}

# Build mapping
mapping = {}
unresolved = []

for pl in playlists:
    title_lower = pl["title"].lower().strip()
    matched_cats = None

    # Try exact keyword match first
    if title_lower in KEYWORD_MAP:
        matched_cats = KEYWORD_MAP[title_lower]
    else:
        # Try partial keyword match
        for keyword, cats in KEYWORD_MAP.items():
            if keyword in title_lower or title_lower in keyword:
                matched_cats = cats
                break

    if matched_cats is not None:
        # Count total videos
        total = sum(categories.get(c, 0) for c in matched_cats)
        mapping[pl["id"]] = {
            "playlist_title": pl["title"],
            "notion_categories": matched_cats,
            "estimated_videos": total,
        }
    else:
        unresolved.append(pl)
        mapping[pl["id"]] = {
            "playlist_title": pl["title"],
            "notion_categories": [],
            "estimated_videos": 0,
        }

# Save mapping
out_path = os.path.join(SCRIPT_DIR, "playlist_category_map.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(mapping, f, indent=2, ensure_ascii=False)

print(f"Generated mapping for {len(mapping)} playlists → {out_path}")
print(f"Resolved: {len(mapping) - len(unresolved)}")
print(f"Unresolved (empty mapping): {len(unresolved)}")
if unresolved:
    print("\nUnresolved playlists:")
    for p in unresolved:
        print(f"  - {p['title']} ({p['id']})")

# Show the specific playlist the user asked about
pid = "4e8e2dbf-bad4-4a56-8365-251a1cfc4a10"
if pid in mapping:
    m = mapping[pid]
    print(f"\n{'='*70}")
    print(f"Playlist: {m['playlist_title']}")
    print(f"Mapped categories: {m['notion_categories']}")
    print(f"Estimated videos: {m['estimated_videos']}")
