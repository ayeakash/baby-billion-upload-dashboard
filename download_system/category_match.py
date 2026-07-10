"""
category_match.py — Use the existing category_mapper.py aliases to reverse-map
playlist names → Notion categories, then find ALL Notion videos for a playlist.

This replaces the old title-matching approach with category-based matching.
"""
import csv, os, re, sys, unicodedata, json
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "pipeline")

APP_CSV      = os.path.join(SCRIPT_DIR, "Latest Videos on The App 18th June - 28 Apr Duplicate.csv")
NOTION_CSV   = os.path.join(SCRIPT_DIR, "notion.csv")
PLAYLIST_CSV = os.path.join(SCRIPT_DIR, "Copy of Playlists Language Tagging - Playlist_new (1).csv")

# ── Re-use the alias tables from category_mapper.py ──────────────────────────

# Age-specific: (age, notion_category_normalized) → playlist_name_normalized
# This is copied from category_mapper.py's _AGE_ALIASES
_AGE_ALIASES = {
    # ── 6+ ────────────────────────────────────────────────────────────────────
    ("6+", "nature"):             "explore nature around",
    ("6+", "seasons"):            "why seasons change",
    ("6+", "about india"):        "know your india",
    ("6+", "countries/geography"):"visit new countries",
    ("6+", "countries"):          "visit new countries",
    ("6+", "science"):            "science made fun",
    ("6+", "space"):              "explore outer space",
    ("6+", "technology"):         "how gadgets work",
    ("6+", "my body"):            "know body parts",
    ("6+", "animals"):            "meet amazing animals",
    ("6+", "plants"):             "watch plants grow",
    ("6+", "food"):               "choose healthy foods",
    ("6+", "good habits"):        "build good habits",
    ("6+", "emotions"):           "understand your feelings",
    ("6+", "safety"):             "stay safe everyday",
    ("6+", "community helpers"):  "what do they do",
    ("6+", "sports"):             "explore different sports",
    ("6+", "knowledge"):          "amazing facts inside",
    # ── 3-6 ───────────────────────────────────────────────────────────────────
    ("3-6", "fruits"):            "name tasty fruits",
    ("3-6", "vegetables"):        "know your vegetables",
    ("3-6", "food items"):        "what's on plate",
    ("3-6", "food"):              "what's on plate",
    ("3-6", "plants"):            "watch plants grow",
    ("3-6", "nature"):            "explore nature around",
    ("3-6", "space"):             "visit outer space",
    ("3-6", "science"):           "science made fun",
    ("3-6", "good habits"):       "build good habits",
    ("3-6", "emotions"):          "understand your feelings",
    ("3-6", "safety"):            "stay safe everyday",
    ("3-6", "community helpers"): "what do they do",
    ("3-6", "vehicles"):          "spot moving vehicles",
    ("3-6", "colors"):            "learn color names",
    ("3-6", "my body"):           "know body parts",
    ("3-6", "toys"):              "discover fun toys",
    ("3-6", "abc"):               "know your alphabets",
    ("3-6", "cvc"):               "read simple words",
    ("3-6", "cvc words"):         "read simple words",
    ("3-6", "phonics"):           "sounds & words",
    ("3-6", "sight words"):       "speak it right",
    ("3-6", "simple sentences"):  "start with sentences",
    ("3-6", "english speaking"):  "speak with confidence",
    ("3-6", "tracing abc"):       "write your alphabets",
    ("3-6", "123"):               "count with confidence",
    ("3-6", "number ordering"):   "place your numbers",
    ("3-6", "shapes"):            "learn your shapes",
    ("3-6", "tracing 123"):       "write your numbers",
    ("3-6", "patterns"):          "play with patterns",
    ("3-6", "addition"):          "add with fun",
    ("3-6", "subtraction"):       "subtract with fun",
    ("3-6", "farm animals"):      "farm animals",
    ("3-6", "wild animals"):      "jungle animals",
    ("3-6", "sea animals"):       "water animals",
    ("3-6", "baby animals"):      "baby animals",
    # ── 0-3 ───────────────────────────────────────────────────────────────────
    ("0-3", "abc"):               "learn your abc",
    ("0-3", "action words"):      "try these actions",
    ("0-3", "words"):             "learn new words",
    ("0-3", "rhymes"):            "sing along rhymes",
    ("0-3", "hindi poems"):       "listen to poems",
    ("0-3", "musical instruments"): "listen and enjoy",
    ("0-3", "music instruments"): "listen and enjoy",
    ("0-3", "123"):               "count with confidence",
    ("0-3", "hindi counting"):    "count in hindi",
    ("0-3", "shapes"):            "spot different shapes",
    ("0-3", "hindi basics"):      "speak simple hindi",
    ("0-3", "farm animals"):      "meet farm friends",
    ("0-3", "birds"):             "spot colorful birds",
    ("0-3", "sea animals"):       "meet ocean animals",
    ("0-3", "insects"):           "meet tiny insects",
    ("0-3", "fruits"):            "name your fruits",
    ("0-3", "vegetables"):        "name your veggies",
    ("0-3", "nature"):            "explore nature around",
    ("0-3", "plants"):            "watch plants grow",
    ("0-3", "animals"):           "meet cute animals",
    ("0-3", "colors"):            "learn color names",
    ("0-3", "toys"):              "find favorite toys",
    ("0-3", "vehicles"):          "spot moving vehicles",
    ("0-3", "my family"):         "meet your family",
    ("0-3", "my body"):           "know body parts",
    ("0-3", "good habits"):       "practice good habits",
    ("0-3", "emotions"):          "understand your feelings",
    ("0-3", "home items"):        "find things around",
    ("0-3", "festivals"):         "celebrate with everyone",
    ("0-3", "clothes"):           "what's everyone wearing",
    ("0-3", "cloths"):            "what's everyone wearing",
    ("0-3", "opposites"):         "learn opposite words",
    ("0-3", "places we go"):      "let's go outside",
    ("0-3", "professions"):       "what do they do",
    # ── Legacy ────────────────────────────────────────────────────────────────
    ("3-6", "relationships"):     "my family",
    ("0-3", "relationships"):     "meet your family",
    ("3-6", "weather"):           "seasons",
    ("6+", "weather"):            "why seasons change",
    ("3-6", "physical movement"): "try these actions",
    ("3-6", "action words"):      "try these actions",
    ("6+", "action words"):       "try these actions",
    ("6+", "phonics"):            "sounds & words",
    ("0-3", "physical movement"): "try these actions",
}


def _normalize(s):
    return " ".join(s.strip().lower().split())


def build_reverse_map():
    """
    Build: playlist_name_lower → set of notion_category_originals
    by reversing the _AGE_ALIASES table.
    """
    reverse = defaultdict(set)  # playlist_name_lower → set of notion categories
    for (age, notion_cat_norm), playlist_name_norm in _AGE_ALIASES.items():
        reverse[playlist_name_norm].add(notion_cat_norm)
    return reverse


def main():
    # ── 1. Build reverse map: playlist_name → notion categories ──────────────
    reverse_map = build_reverse_map()

    # ── 2. Load playlists from CSV ───────────────────────────────────────────
    playlists = {}
    with open(PLAYLIST_CSV, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pid = row["playlist_id"].strip()
            title = row["title"].strip()
            playlists[pid] = title

    # ── 3. Target playlist ───────────────────────────────────────────────────
    target_pid = sys.argv[1] if len(sys.argv) > 1 else "4e8e2dbf-bad4-4a56-8365-251a1cfc4a10"
    target_name = playlists.get(target_pid, "UNKNOWN")
    target_key = _normalize(target_name)

    print(f"Playlist: {target_name} ({target_pid})")
    print(f"Normalized key: '{target_key}'")

    # Find which Notion categories map to this playlist
    mapped_categories = reverse_map.get(target_key, set())

    # Also check if the playlist name itself matches a Notion category directly
    # (e.g. "Counting", "Prepositions" might be both playlist name AND Notion category)
    mapped_categories.add(target_key)

    print(f"\nMapped Notion categories (from aliases): {sorted(mapped_categories)}")

    # ── 4. Load Notion CSV and find all videos in those categories ────────────
    notion_videos = []
    all_notion_cats = set()
    with open(NOTION_CSV, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            vname = (row.get("Video Name") or "").strip()
            cat = (row.get("Category") or "").strip()
            hindi_link = (row.get("Final Video Hindi Link") or "").strip()
            english_link = (row.get("Final Video English Link") or "").strip()
            if not vname:
                continue

            all_notion_cats.add(cat)

            # Check if this video's category matches any of our mapped categories
            # Notion categories can be compound like "Action words, My Body"
            cat_parts = [_normalize(c) for c in cat.split(",")]
            matched = any(cp in mapped_categories for cp in cat_parts)

            if matched:
                link = hindi_link or english_link or ""
                notion_videos.append({
                    "video_name": vname,
                    "category": cat,
                    "hindi_link": hindi_link,
                    "english_link": english_link,
                    "has_link": bool(link),
                })

    # ── 5. Report ────────────────────────────────────────────────────────────
    with_link = sum(1 for v in notion_videos if v["has_link"])
    print(f"\n{'='*80}")
    print(f"RESULTS: Notion videos for playlist '{target_name}'")
    print(f"{'='*80}")
    print(f"Total Notion videos found: {len(notion_videos)}")
    print(f"  With Drive link: {with_link}")
    print(f"  Without link:    {len(notion_videos) - with_link}")

    # Group by category
    by_cat = defaultdict(list)
    for v in notion_videos:
        by_cat[v["category"]].append(v)

    print(f"\nBreakdown by Notion category:")
    for cat, vids in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        links = sum(1 for v in vids if v["has_link"])
        print(f"  {cat:<40} {len(vids):>4} videos ({links} with link)")

    print(f"\n{'─'*80}")
    print(f"Full video list:")
    print(f"{'─'*80}")
    for i, v in enumerate(notion_videos, 1):
        link = v["hindi_link"] or v["english_link"] or "(no link)"
        status = "✓" if v["has_link"] else "✗"
        print(f"  {i:>3}. [{status}] {v['video_name']:<50} | {v['category']:<30} | {link[:60]}")


if __name__ == "__main__":
    main()
