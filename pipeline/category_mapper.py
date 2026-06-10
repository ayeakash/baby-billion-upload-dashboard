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
    """Lowercase + collapse whitespace for fuzzy matching, then apply aliases."""
    normalized = " ".join(cat.strip().lower().split())
    return _KNOWN_ALIASES.get(normalized, normalized)


# Notion name (normalized) → Admin dashboard name (normalized)
# These handle cases where Notion uses a different spelling than the dashboard
_KNOWN_ALIASES: dict[str, str] = {
    "varnamala": "varnmala",    # Notion says "Varnamala", dashboard says "Varnmala"
    "relationships": "my family",        # Notion says "Relationships", dashboard says "My Family"
    "music instruments": "musical instruments",  # Notion says "Music instruments", CSV says "Musical Instruments"
    "weather": "seasons",      # Notion says "Weather", dashboard has "Seasons"
    "physical movement": "action words",  # Notion says "Physical Movement", dashboard has "Action Words"
}


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
        get_category_fields("3-6", "CVC Words")       -> ("English", "CVC Words")
        get_category_fields("3-6", "ABC")              -> ("English", "ABC")
        get_category_fields("3-6", "Good habits")      -> ("", "Good Habits")
        get_category_fields("3-6", "Colors")           -> ("", "Colors")
        get_category_fields("3-6", "Animals")          -> ("Animals", "Animals")
        get_category_fields("0-3", "ABC")              -> ("", "ABC")
    """
    _load()

    age = _normalize_age(age_group)
    cat = _normalize_cat(notion_category)

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
    log.warning(
        f"  [WARN] No category mapping found for: age='{age_group}', "
        f"category='{notion_category}'. Using raw value — check categories mapping.csv!"
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
    cat = _normalize_cat(notion_category)

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
