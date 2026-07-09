"""
category_mapper.py — Loads 'categories mapping.csv' and maps
(age_group, notion_category) → (parent_category, exact_category_name)
as required by the BabyBillion admin site.

Rules:
  - Always use the EXACT category name from the CSV (case-sensitive)
  - Parent is taken from Column 2; empty means no parent (standalone category)
  - Matching is case-insensitive and whitespace-tolerant
  - If no match found, logs a warning and falls back gracefully

Usage:
    from category_mapper import get_category_fields
    parent, category = get_category_fields(age_group="3-6", notion_category="CVC Words")
    # → ("English", "CVC Words")
"""
from __future__ import annotations

import os
import csv
import logging

log = logging.getLogger(__name__)

MAPPING_CSV = os.path.join(os.path.dirname(__file__), "categories mapping.csv")

# ── Internal lookup: (age_str, category_lower) → (parent, exact_category) ────
_LOOKUP: dict[tuple, tuple] = {}
_LOADED = False


def _normalize_age(age: str) -> str:
    """Normalize age group strings to canonical form."""
    a = age.strip().lower().replace(" ", "")
    if "under3" in a or "0-3" in a or a in ("under3", "03", "<3"):
        return "0-3"
    if "3-6" in a or "36" in a:
        return "3-6"
    if "6+" in a or "6plus" in a or a in ("6+", "6+"):
        return "6+"
    return a


def _normalize_cat(cat: str) -> str:
    """Lowercase + collapse whitespace for fuzzy matching."""
    return " ".join(cat.strip().lower().split())


# ── Aliases: Notion name (normalized) → CSV Playlist Name (normalized) ────────
# Global aliases apply to all age groups (where the mapping is the same everywhere)
_GLOBAL_ALIASES: dict[str, str] = {
    "varnamala": "varnmala",    # Notion says "Varnamala", dashboard says "Varnmala"
    "alladin": "aladdin",      # Fix common typo in Notion
}

# Age-specific aliases: (age, notion_name_normalized) → csv_name_normalized
# Maps old Notion category names to the new "3Word Promise" playlist names.
# Generated from "Playlists new names - Sheet1.csv".
_AGE_ALIASES: dict[tuple[str, str], str] = {
    # ── 6+ ────────────────────────────────────────────────────────────────────
    ("6+", "opposites"):          "learn opposite words",
    ("6+", "learn opposites"):    "learn opposite words",
    ("6+", "nature"):             "explore nature around",
    ("6+", "seasons"):            "why seasons change",
    ("6+", "about india"):        "know your india",
    ("6+", "countries/geography"):"visit new countries",
    ("6+", "countries"):          "visit new countries",
    ("6+", "science"):            "discover science secrets",
    ("6+", "space"):              "explore outer space",
    ("6+", "technology"):         "how gadgets work",
    ("6+", "my body"):            "know body parts",
    ("6+", "animals"):            "meet amazing animals",
    ("6+", "plants"):             "watch plants grow",
    ("6+", "food"):               "choose healthy foods",
    ("6+", "good habits"):        "build good habits",
    ("6+", "emotions"):           "understand your feelings",
    ("6+", "safety"):             "stay safe everyday",
    ("6+", "community helpers"):  "meet everyday helpers",
    ("6+", "sports"):             "explore different sports",
    ("6+", "knowledge"):          "amazing facts inside",

    # ── 3-6 ───────────────────────────────────────────────────────────────────
    ("3-6", "opposites"):         "learn opposite words",
    ("3-6", "learn opposites"):   "learn opposite words",
    ("3-6", "fruits"):            "name tasty fruits",
    ("3-6", "vegetables"):        "know your vegetables",
    ("3-6", "food items"):        "what's on plate",
    ("3-6", "food"):              "what's on plate",
    ("3-6", "plants"):            "watch plants grow",
    ("3-6", "nature"):            "explore nature around",
    ("3-6", "space"):             "visit outer space",
    ("3-6", "science"):           "science made fun",
    ("3-6", "good habits"):       "build good habits",
    ("3-6", "emotions"):          "what's that feeling",
    ("3-6", "safety"):            "stay safe everyday",
    ("3-6", "community helpers"): "meet helpful people",
    ("3-6", "vehicles"):          "spot cool vehicles",
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
    ("0-3", "emotions"):          "how are you",
    ("0-3", "home items"):        "find things around",
    ("0-3", "festivals"):         "celebrate with everyone",
    ("0-3", "clothes"):           "what's everyone wearing",
    ("0-3", "cloths"):            "what's everyone wearing",
    ("0-3", "opposites"):         "learn opposite words",
    ("0-3", "learn opposites"):   "learn opposite words",
    ("0-3", "places we go"):      "let's go outside",
    ("0-3", "professions"):       "what do they do",

    # ── Legacy Notion aliases (kept from previous mapping) ────────────────────
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



def _resolve_alias(age: str, normalized_cat: str) -> str:
    """Resolve a Notion category name to its CSV playlist name, using
    age-specific aliases first, then global aliases, then raw name."""
    # Try age-specific alias first
    age_key = (age, normalized_cat)
    if age_key in _AGE_ALIASES:
        return _AGE_ALIASES[age_key]
    # Then global alias
    return _GLOBAL_ALIASES.get(normalized_cat, normalized_cat)



def _load():
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    if not os.path.isfile(MAPPING_CSV):
        log.error(f"Category mapping CSV not found: {MAPPING_CSV}")
        return

    with open(MAPPING_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            age    = _normalize_age(row.get("Age", "").strip())
            parent = row.get("Parent Category", "").strip()
            cat    = row.get("Playlist Name", "").strip()

            if not cat or cat.lower() in ("playlist name",):  # skip header-like rows
                continue

            key = (age, _normalize_cat(cat))
            _LOOKUP[key] = (parent, cat)

            # Also register the parent itself as a standalone category
            # (e.g., "Animals" as parent → allows matching notion_category="Animals")
            if parent:
                parent_key = (age, _normalize_cat(parent))
                if parent_key not in _LOOKUP:
                    _LOOKUP[parent_key] = (parent, parent)

    log.info(f"Category mapper loaded {len(_LOOKUP)} entries from {os.path.basename(MAPPING_CSV)}")


def get_category_fields(age_group: str, notion_category: str) -> tuple[str, str]:
    """
    Given an age group and the category name from Notion, return:
        (parent_category, exact_category_name)

    Both values are exactly as they appear in 'categories mapping.csv'.
    If no match is found, returns ("", notion_category) and logs a warning.

    Examples:
        get_category_fields("3-6", "CVC")              -> ("English", "Read Simple Words")
        get_category_fields("3-6", "ABC")               -> ("English", "Know Your Alphabets")
        get_category_fields("3-6", "Good habits")       -> ("", "Build Good Habits")
        get_category_fields("3-6", "Colors")            -> ("", "Learn Color Names")
        get_category_fields("3-6", "Animals")           -> ("Animals", "Animals")
        get_category_fields("0-3", "ABC")               -> ("", "Learn Your ABC")
    """
    _load()

    age = _normalize_age(age_group)
    cat = _resolve_alias(age, _normalize_cat(notion_category))

    # ── Exact match ────────────────────────────────────────────────────────────
    key = (age, cat)
    if key in _LOOKUP:
        parent, exact = _LOOKUP[key]
        log.debug(f"  Category match [{age}] '{notion_category}' -> parent='{parent}', cat='{exact}'")
        return parent, exact

    # ── Partial / prefix match (handles "English speaking" vs "English Speaking") ──
    for (lk_age, lk_cat), (parent, exact) in _LOOKUP.items():
        if lk_age == age and (lk_cat.startswith(cat) or cat.startswith(lk_cat)):
            log.debug(f"  Category partial match [{age}] '{notion_category}' -> '{exact}'")
            return parent, exact

    # ── Age-agnostic fallback (try other age groups) ───────────────────────────
    for (lk_age, lk_cat), (parent, exact) in _LOOKUP.items():
        if _normalize_cat(lk_cat) == cat:
            log.warning(
                f"  Category '{notion_category}' not found for age '{age_group}', "
                f"using match from age '{lk_age}': parent='{parent}', cat='{exact}'"
            )
            return parent, exact

    # ── No match ───────────────────────────────────────────────────────────────
    # Unmapped Notion categories go into categories_name via exact_cat
    log.warning(
        f"  [WARN] No category mapping found for: age='{age_group}', "
        f"category='{notion_category}'. Using as category — check categories mapping.csv!"
    )
    return "", notion_category


def is_valid_category(age_group: str, notion_category: str) -> bool:
    """
    Return True if (age_group, notion_category) resolves to a known entry
    in the categories mapping CSV.  Uses the same matching logic as
    get_category_fields (exact → partial) but does NOT fall back to
    age-agnostic matching or raw passthrough.
    """
    _load()
    age = _normalize_age(age_group)
    cat = _resolve_alias(age, _normalize_cat(notion_category))

    # Exact match
    if (age, cat) in _LOOKUP:
        return True

    # Partial / prefix match (same as get_category_fields)
    for (lk_age, lk_cat) in _LOOKUP:
        if lk_age == age and (lk_cat.startswith(cat) or cat.startswith(lk_cat)):
            return True

    return False


def list_all(age_group: str | None = None) -> list[tuple]:
    """Debug helper: list all known (age, parent, category) triples."""
    _load()
    results = []
    for (age, cat_lower), (parent, exact) in sorted(_LOOKUP.items()):
        if age_group and _normalize_age(age_group) != age:
            continue
        results.append((age, parent, exact))
    return results
