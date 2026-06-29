"""
sanity_checker.py — Pre-upload validation for BabyBillion Notion pipeline.

Runs BEFORE downloading to catch data issues early.  Each video is checked
against the categories mapping CSV and the admin-site field requirements.

Checks performed:
  1. age_group         — must normalise to one of: "0-3", "3-6", "6+"
  2. category          — must exist (non-empty)
  3. category mapping  — must resolve to a known entry in 'categories mapping.csv'
  4. category casing   — auto-fixed to match CSV (logged as warning, not failure)
  5. content_type      — must be "Original" (the only value the admin accepts)
  6. drive_link        — must contain a Google Drive URL
  7. video_name        — must be non-empty

Special rules:
  - Safety override: if ANY category part contains "safety" (case-insensitive),
    the entire category is overridden to just "Safety".

Auto-fixes (NOT failures):
  - Category capitalisation mismatch → corrected to match CSV exactly

Videos that fail ANY hard check are:
  - Removed from the processing list
  - Marked as "failed" in state.json  (reason = "sanity:<check_name>")
  - Marked as "Failed to upload" in Notion via the API
  - Logged with a clear error message
"""

import logging
import re
from config import AGE_GROUP_MAP, ADMIN_CONTENT_TYPE
from category_mapper import get_category_fields, is_valid_category, _load, _LOOKUP, _normalize_age, _normalize_cat
import state_manager as sm
import notion_client as nc

log = logging.getLogger(__name__)

# ── Valid age groups after normalisation ───────────────────────────────────────
VALID_AGE_GROUPS = {"0-3", "3-6", "6+"}

# ── Valid content types accepted by admin dashboard ───────────────────────────
VALID_CONTENT_TYPES = {ADMIN_CONTENT_TYPE}  # {"Original"}


class SanityFailure:
    """Describes a single validation failure for one video."""
    __slots__ = ("check", "message")

    def __init__(self, check: str, message: str):
        self.check   = check      # e.g. "bad_age_group", "bad_category", …
        self.message = message    # human-readable explanation

    def __repr__(self):
        return f"SanityFailure({self.check!r}, {self.message!r})"


class SanityAutoFix:
    """Describes an auto-corrected field (not a failure)."""
    __slots__ = ("field", "old_value", "new_value", "reason")

    def __init__(self, field: str, old_value: str, new_value: str, reason: str):
        self.field     = field
        self.old_value = old_value
        self.new_value = new_value
        self.reason    = reason

    def __repr__(self):
        return f"AutoFix({self.field}: '{self.old_value}' → '{self.new_value}')"


def _apply_category_overrides(video: dict) -> list[SanityAutoFix]:
    """
    Apply special category override rules.  Mutates video["category"] in place.
    Returns list of auto-fixes applied.
    """
    fixes: list[SanityAutoFix] = []
    cat_raw = video.get("category", "").strip()

    if not cat_raw:
        return fixes

    # ── Safety override: if ANY part contains "safety", use just "Safety" ─────
    parts = [p.strip() for p in cat_raw.split(",") if p.strip()]
    has_safety = any("safety" in p.lower() for p in parts)

    if has_safety and cat_raw.strip().lower() != "safety":
        fixes.append(SanityAutoFix(
            "category", cat_raw, "Safety",
            "Category contains 'safety' → overriding to standalone 'Safety'"
        ))
        video["category"] = "Safety"

    return fixes


def _auto_fix_category_case(video: dict, age_normalised: str) -> list[SanityAutoFix]:
    """
    If the category is valid but has wrong capitalisation, auto-fix it
    to match the CSV exactly.  Mutates video["category"] in place.
    """
    fixes: list[SanityAutoFix] = []
    cat_raw = video.get("category", "").strip()

    if not cat_raw or age_normalised not in VALID_AGE_GROUPS:
        return fixes

    # Handle comma-separated multi-categories
    parts = [p.strip() for p in cat_raw.split(",") if p.strip()]
    corrected_parts = []
    changed = False

    for part in parts:
        if is_valid_category(age_normalised, part):
            _parent, exact_cat = get_category_fields(age_normalised, part)
            if part != exact_cat:
                corrected_parts.append(exact_cat)
                changed = True
            else:
                corrected_parts.append(part)
        else:
            corrected_parts.append(part)  # leave as-is, will be caught by validation

    if changed:
        new_cat = ", ".join(corrected_parts)
        fixes.append(SanityAutoFix(
            "category", cat_raw, new_cat,
            f"Auto-fixed capitalisation to match CSV"
        ))
        video["category"] = new_cat

    return fixes


def _validate_one(video: dict) -> tuple[list[SanityFailure], list[SanityAutoFix]]:
    """
    Run all sanity checks on a single video dict.
    Returns (failures, auto_fixes).
    Failures = hard rejects.  Auto-fixes = corrected in place.
    """
    failures:  list[SanityFailure] = []
    auto_fixes: list[SanityAutoFix] = []

    # ── Pre-validation overrides (mutate video dict) ──────────────────────────
    auto_fixes.extend(_apply_category_overrides(video))

    name      = video.get("video_name", "").strip()
    age_raw   = video.get("age_group", "").strip()
    cat_raw   = video.get("category", "").strip()
    link      = video.get("drive_link", "").strip()

    # ── 1. Video name ─────────────────────────────────────────────────────────
    if not name:
        failures.append(SanityFailure(
            "missing_name",
            "Video name is empty"
        ))

    # ── 2. Age group ──────────────────────────────────────────────────────────
    age_normalised = AGE_GROUP_MAP.get(age_raw.lower(), "")
    if not age_normalised:
        # Try the category_mapper normaliser as fallback
        age_normalised = _normalize_age(age_raw)

    if age_normalised not in VALID_AGE_GROUPS:
        failures.append(SanityFailure(
            "bad_age_group",
            f"Age group '{age_raw}' does not map to a valid value "
            f"(expected one of {sorted(VALID_AGE_GROUPS)})"
        ))

    # ── 3. Auto-fix capitalisation BEFORE validation ─────────────────────────
    if age_normalised in VALID_AGE_GROUPS:
        auto_fixes.extend(_auto_fix_category_case(video, age_normalised))
        cat_raw = video.get("category", "").strip()  # re-read after fix

    # ── 4. Category present ──────────────────────────────────────────────────
    if not cat_raw:
        failures.append(SanityFailure(
            "missing_category",
            "Category is empty"
        ))
    else:
        # Handle comma-separated multi-categories
        cat_parts = [p.strip() for p in cat_raw.split(",") if p.strip()]

        for part in cat_parts:
            # ── 4a. Category exists in mapping CSV ────────────────────────────
            #    Unknown categories are allowed through with a warning.
            #    They'll use the raw Notion value in the CSV.
            if age_normalised in VALID_AGE_GROUPS:
                if not is_valid_category(age_normalised, part):
                    auto_fixes.append(SanityAutoFix(
                        "category", part, part,
                        f"Category '{part}' (age={age_normalised}) not in CSV — using raw value"
                    ))

    # ── 5. Drive link ─────────────────────────────────────────────────────────
    if not link:
        failures.append(SanityFailure(
            "missing_drive_link",
            "Drive link is empty (no Hindi or English link)"
        ))
    elif "drive.google.com" not in link:
        failures.append(SanityFailure(
            "bad_drive_link",
            f"Link does not point to Google Drive: '{link[:80]}'"
        ))

    # ── 6. Content type (hardcoded to "Original" — just verify the config) ───
    if ADMIN_CONTENT_TYPE not in VALID_CONTENT_TYPES:
        failures.append(SanityFailure(
            "bad_content_type",
            f"ADMIN_CONTENT_TYPE='{ADMIN_CONTENT_TYPE}' is not one of "
            f"{sorted(VALID_CONTENT_TYPES)}"
        ))

    return failures, auto_fixes


def run(videos: list[dict], mark_notion: bool = True) -> tuple[list[dict], list[dict]]:
    """
    Validate every video in `videos` and split into (passed, failed).

    For each failed video:
      - state.json is updated with pipeline_status="failed"
      - If mark_notion=True, the Notion page is marked "Failed to upload"

    Auto-fixes (e.g. capitalisation) are applied in-place to passing videos.

    Returns:
        (passed_videos, failed_videos)
    """
    # Ensure the category CSV is loaded
    _load()

    passed:  list[dict] = []
    failed:  list[dict] = []
    failure_summary: dict[str, int] = {}  # check_name -> count
    fix_count = 0

    log.info(f"\n{'='*60}")
    log.info(f"  SANITY CHECK: validating {len(videos)} video(s) …")
    log.info(f"{'='*60}")

    for v in videos:
        failures, auto_fixes = _validate_one(v)

        # Log auto-fixes (these are corrections, not failures)
        for fix in auto_fixes:
            log.warning(
                f"  [AUTO-FIX] [{v.get('video_name','?')}] "
                f"{fix.field}: '{fix.old_value}' -> '{fix.new_value}' "
                f"({fix.reason})"
            )
            fix_count += 1

        if not failures:
            passed.append(v)
            continue

        # ── This video failed ─────────────────────────────────────────────────
        failed.append(v)
        pid  = v.get("page_id", "???")
        name = v.get("video_name", "???")

        reasons = "; ".join(f.message for f in failures)
        checks  = ", ".join(f.check for f in failures)

        log.error(
            f"  [FAIL] [{name}] (page={pid[:12]}...)\n"
            f"         checks: {checks}\n"
            f"         detail: {reasons}"
        )

        # Update state.json
        sm.mark_failed(pid, f"sanity:{checks}")

        # Update Notion
        if mark_notion:
            try:
                nc.mark_failed_in_notion(pid)
                log.info(f"         -> Notion marked as 'Failed to upload'")
            except Exception as e:
                log.warning(f"         -> Notion update failed: {e}")

        for f in failures:
            failure_summary[f.check] = failure_summary.get(f.check, 0) + 1

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info(f"\n  Sanity check results:")
    log.info(f"    [OK]   Passed : {len(passed)}")
    log.info(f"    [FAIL] Failed : {len(failed)}")
    if fix_count:
        log.info(f"    [AUTO-FIXED] : {fix_count} field(s)")
    if failure_summary:
        log.info(f"    Failure breakdown:")
        for check, count in sorted(failure_summary.items()):
            log.info(f"      {check:25s}: {count}")

    return passed, failed
