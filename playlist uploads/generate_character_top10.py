"""
generate_character_top10.py
============================
Reads Characters.csv for character→title mapping, then looks up correct CMS
video_ids from 'Latest Videos on The App 18th June - 21 July.csv'.
Generates one CSV per character (top 10 videos) for the CMS dashboard.

Usage:
    python generate_character_top10.py          # generate CSVs
    python generate_character_top10.py --dry-run # show plan without writing
"""

import csv
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict
from typing import Optional, List, Dict

SCRIPT_DIR = Path(__file__).resolve().parent
CHARACTERS_CSV = SCRIPT_DIR / "Characters.csv"
CMS_VIDEOS_CSV = SCRIPT_DIR / "Latest Videos on The App 18th June - 21 July.csv"
OUTPUT_DIR = SCRIPT_DIR / "BabyBillion_Playlist_TopVideos"

# The 11 solo characters to generate CSVs for
SOLO_CHARACTERS = [
    "arjun", "mia", "tara", "priya", "veer",
    "zoya", "jai", "riya", "meera", "teja", "guddi",
]

# Typo/alias mapping → normalized solo character name
CHARACTER_ALIASES = {
    "arjin":  "arjun",
    "mai":    "mia",
    "prya":   "priya",
    "veera":  "veer",
    "piya":   "priya",
    "zolya":  "zoya",
    "zara":   "zoya",
}

# CSV format expected by the CMS dashboard
NEW_CSV_HEADERS = [
    "video_id",
    "title",
    "ranking",
]

TOP_N = 10


def normalize_character(raw: str) -> Optional[str]:
    """Return normalized solo character name, or None if not a solo character."""
    name = raw.strip().lower()
    if name in CHARACTER_ALIASES:
        name = CHARACTER_ALIASES[name]
    if name in SOLO_CHARACTERS:
        return name
    return None


def title_case_character(name: str) -> str:
    return name.capitalize()


def load_cms_video_ids() -> Dict[str, str]:
    """Load title → CMS video_id mapping from the accurate CMS export."""
    cms_map = {}
    with CMS_VIDEOS_CSV.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row.get("video_title", "").strip()
            vid = row.get("video_id", "").strip()
            if title and vid:
                cms_map[title] = vid
    return cms_map


def read_characters_csv(cms_map: Dict[str, str]) -> Dict[str, List[dict]]:
    """Read Characters.csv, group by character, deduplicate, and resolve CMS IDs.

    Only includes videos that have a matching CMS video_id.
    """
    all_rows = []
    with CHARACTERS_CSV.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_rows.append(row)

    # Deduplicate by (character, title) — keep unique titles per character
    seen = set()
    char_videos = defaultdict(list)  # type: Dict[str, List[dict]]

    for row in all_rows:
        char_raw = row.get("Character", "").strip()
        char = normalize_character(char_raw)
        if char is None:
            continue

        title = row.get("title", "").strip()
        key = (char, title)

        if key in seen:
            continue
        seen.add(key)

        # Look up the correct CMS video_id
        cms_vid = cms_map.get(title)
        if cms_vid is None:
            continue  # skip videos not in CMS

        # Store with the correct CMS video_id
        row["cms_video_id"] = cms_vid
        char_videos[char].append(row)

    return char_videos


def generate_csv(character: str, videos: List[dict], dry_run: bool = False) -> Optional[Path]:
    """Generate a top-10 CSV for a character with correct CMS video_ids."""
    top_videos = videos[:TOP_N]
    cat_name = title_case_character(character)

    filename = f"{cat_name}.csv"
    outpath = OUTPUT_DIR / filename

    if dry_run:
        print(f"  [DRY-RUN] Would write {filename} ({len(top_videos)} rows)")
        for v in top_videos:
            print(f"    - {v['cms_video_id'][:12]}... | {v['title']}")
        return None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with outpath.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NEW_CSV_HEADERS)
        writer.writeheader()

        for rank, video in enumerate(top_videos, start=1):
            writer.writerow({
                "video_id": video["cms_video_id"],
                "title":    video.get("title", "").strip(),
                "ranking":  rank,
            })

    return outpath


def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("  Character Top-10 CSV Generator")
    print("=" * 60)
    print(f"  Characters: {CHARACTERS_CSV.name}")
    print(f"  CMS IDs:    {CMS_VIDEOS_CSV.name}")
    print(f"  Output:     {OUTPUT_DIR}")
    print(f"  Mode:       {'DRY RUN' if dry_run else 'GENERATE'}")
    print()

    # Load CMS video_id mapping
    cms_map = load_cms_video_ids()
    print(f"  Loaded {len(cms_map)} CMS video_ids")
    print()

    # Read Characters.csv with CMS ID resolution
    groups = read_characters_csv(cms_map)

    print(f"  Found {len(groups)} solo characters:")
    for char in SOLO_CHARACTERS:
        count = len(groups.get(char, []))
        marker = "[OK]" if count >= TOP_N else "[!!]"
        print(f"    {marker} {title_case_character(char):10s} → {count:3d} videos with CMS IDs"
              f" (will use top {min(count, TOP_N)})")

    print()

    # Generate CSVs
    generated = []
    for char in SOLO_CHARACTERS:
        videos = groups.get(char, [])
        if not videos:
            print(f"  SKIP: No videos for '{char}'")
            continue

        outpath = generate_csv(char, videos, dry_run=dry_run)
        if outpath:
            generated.append((char, outpath))
            print(f"  DONE: {outpath.name} ({min(len(videos), TOP_N)} rows)")

    print()
    print("=" * 60)
    if dry_run:
        print(f"  Dry run complete. Would generate {len(SOLO_CHARACTERS)} CSV files.")
    else:
        print(f"  Generated {len(generated)} CSV files in {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
