"""
match_videos.py — Match app CSV titles with Notion CSV video names to find
Google Drive links for vertical video downloads.

Sanitizes both sides the same way and reports match statistics.
"""
import csv
import os
import re
import sys
import unicodedata

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

APP_CSV    = os.path.join(SCRIPT_DIR,
    "Latest Videos on The App 18th June - 28 Apr Duplicate.csv")
NOTION_CSV = os.path.join(SCRIPT_DIR, "notion.csv")


def sanitize(name: str) -> str:
    """Normalize a name for matching: lowercase, ASCII, underscores."""
    # Remove zero-width and invisible Unicode chars
    name = re.sub(r'[\u200b\u200c\u200d\u2060\ufeff\u2068\u2069]', '', name)
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"[\s]+", "_", name.strip())
    name = name.strip("_").lower()
    return name


def main():
    # Load Notion CSV → build lookup: sanitized_name → row
    notion_lookup = {}  # sanitized_name -> { video_name, drive_link, ... }
    notion_raw = []
    with open(NOTION_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vname = (row.get("Video Name") or "").strip()
            hindi_link = (row.get("Final Video Hindi Link") or "").strip()
            english_link = (row.get("Final Video English Link") or "").strip()
            if not vname:
                continue
            notion_raw.append(row)
            key = sanitize(vname)
            if key:
                notion_lookup[key] = {
                    "video_name": vname,
                    "hindi_link": hindi_link,
                    "english_link": english_link,
                    "category": (row.get("Category") or "").strip(),
                    "age_group": (row.get("Age Group") or "").strip(),
                    "status": (row.get("Status") or "").strip(),
                }

    print(f"Notion CSV: {len(notion_raw)} rows with names, {len(notion_lookup)} unique sanitized keys")

    # Load App CSV → try matching each title
    matched = 0
    matched_with_link = 0
    unmatched = []
    total_app = 0

    # Filter for a specific playlist if provided
    playlist_filter = sys.argv[1] if len(sys.argv) > 1 else None

    with open(APP_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if playlist_filter:
                pid = (row.get("playlist_id") or "").strip().lower()
                if pid != playlist_filter.lower():
                    continue

            title = (row.get("title") or "").strip()
            if not title:
                continue
            total_app += 1
            key = sanitize(title)

            if key in notion_lookup:
                matched += 1
                n = notion_lookup[key]
                has_link = bool(n["hindi_link"]) or bool(n["english_link"])
                if has_link:
                    matched_with_link += 1
            else:
                unmatched.append((title, key))

    print(f"\nApp CSV: {total_app} videos" +
          (f" (filtered to playlist {playlist_filter})" if playlist_filter else ""))
    print(f"  Matched:          {matched}/{total_app} ({100*matched/max(total_app,1):.1f}%)")
    print(f"  With Drive link:  {matched_with_link}/{total_app} ({100*matched_with_link/max(total_app,1):.1f}%)")
    print(f"  Unmatched:        {len(unmatched)}/{total_app}")

    if unmatched and len(unmatched) <= 30:
        print(f"\nUnmatched titles:")
        for title, key in unmatched[:30]:
            print(f"  '{title}' -> sanitized: '{key}'")
    elif unmatched:
        print(f"\nFirst 20 unmatched titles:")
        for title, key in unmatched[:20]:
            print(f"  '{title}' -> sanitized: '{key}'")


if __name__ == "__main__":
    main()
