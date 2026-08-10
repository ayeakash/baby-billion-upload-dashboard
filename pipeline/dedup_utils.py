"""
dedup_utils.py — Unified normalization functions for deduplication.

All dedup checks across the pipeline MUST use these functions to ensure
consistent key generation.  This eliminates mismatches between:
  - stage_fetch guards
  - batcher guards
  - retry script guards
  - state.json lookups

Usage:
    from dedup_utils import normalize_video_key, normalize_age, normalize_name

    key = normalize_video_key(video_name, age_group)
    # Returns a (str, str) tuple: (normalized_name, normalized_age)
"""
from __future__ import annotations

import re
from config import AGE_GROUP_MAP


def normalize_age(age_raw: str) -> str:
    """
    Normalize age group to one of: '0-3', '3-6', '6+'.
    Uses config.AGE_GROUP_MAP first, then fallback heuristics.
    Returns empty string if unrecognised.
    """
    if not age_raw:
        return ""
    key = age_raw.strip().lower()

    # Exact match from config
    mapped = AGE_GROUP_MAP.get(key, "")
    if mapped:
        return mapped

    # Fallback: strip spaces and try common patterns
    compact = key.replace(" ", "")
    if "under3" in compact or "0-3" in compact:
        return "0-3"
    if "3-6" in compact or "36" in compact:
        return "3-6"
    if "6+" in compact or "6plus" in compact:
        return "6+"

    return ""


def normalize_name(name: str) -> str:
    """
    Normalize a video name for dedup matching.
    Strips non-word characters, collapses underscores, lowercases.

    This is the SINGLE source of truth for name normalization.
    """
    if not name:
        return ""
    # Replace all non-word characters with underscore
    n = re.sub(r"[^\w]", "_", name)
    # Collapse consecutive underscores
    n = re.sub(r"_+", "_", n)
    # Strip leading/trailing underscores and lowercase
    n = n.strip("_").lower()
    return n


def normalize_video_key(video_name: str, age_group: str) -> tuple[str, str]:
    """
    Generate a canonical (name, age) dedup key for a video.
    Use this everywhere deduplication is checked.
    """
    return (normalize_name(video_name), normalize_age(age_group))


def build_uploaded_keys_from_state(state_all: dict) -> set[tuple[str, str, str]]:
    """
    Scan state.json and return a set of (normalized_name, normalized_age, lang_suffix)
    for all videos with pipeline_status == 'uploaded'.

    IMPORTANT: lang_suffix allows Hindi and English versions of the same video
    to be tracked separately — uploading both versions is allowed.
    """
    keys: set[tuple[str, str, str]] = set()
    for _pid, rec in state_all.items():
        if not isinstance(rec, dict):
            continue
        if rec.get("pipeline_status") != "uploaded":
            continue
        name = rec.get("video_name", "")
        age = rec.get("age_group", "")
        lang_suffix = rec.get("lang_suffix", "")  # Include language suffix
        key = normalize_video_key(name, age)
        if key[0]:  # only add if name is non-empty
            keys.add((key[0], key[1], lang_suffix))
    return keys
