"""
Restore Notion pages from trash — AI Sprint Database.

Finds all pages in the "AI Sprint" multi-data-source database that were
trashed today by a specific user, and restores them.

Handles Notion's "multiple data sources" databases by using the search API
to find trashed pages (since direct database query is not supported for
multi-data-source DBs).

Usage:
    1. Set your Notion integration token:
           set NOTION_API_KEY=secret_xxxxxxxxxxxxx
    2. Run:
           python restore_trash.py
           python restore_trash.py --dry-run
           python restore_trash.py --user "Someone Else"
           python restore_trash.py --date 2026-05-25
"""

import os
import sys
import io
import json
import argparse
from datetime import datetime, timezone, timedelta, date
from urllib import request, error

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# --- Config -------------------------------------------------------------------

API_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"
DATABASE_ID = "34463e60-e8f4-805a-85e0-fff4388938c0"  # AI Sprint master board
IST = timezone(timedelta(hours=5, minutes=30))


# --- API Helpers --------------------------------------------------------------

def get_api_key() -> str:
    key = os.environ.get("NOTION_API_KEY")
    if not key:
        print("ERROR: NOTION_API_KEY environment variable is not set.")
        print("  -> Create an internal integration at https://www.notion.so/my-integrations")
        print("  -> Then run:  set NOTION_API_KEY=secret_xxxxxxxxxx")
        sys.exit(1)
    return key


def notion_request(method: str, endpoint: str, body: dict | None = None) -> tuple[dict, int]:
    """Make an authenticated request to the Notion API. Returns (data, status_code)."""
    api_key = get_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": API_VERSION,
        "Content-Type": "application/json",
    }
    url = f"{BASE_URL}{endpoint}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = request.Request(url, data=data, headers=headers, method=method)

    try:
        with request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return json.loads(err_body), e.code
        except json.JSONDecodeError:
            return {"error": err_body}, e.code


# --- Core Logic ---------------------------------------------------------------

def find_all_trashed_pages(database_id: str) -> list[dict]:
    """
    Find trashed pages belonging to the database.

    Since this is a multi-data-source database, the /databases/{id}/query
    endpoint doesn't work. Instead we use the search API to scan all pages
    the integration can see and filter for those that are in_trash=True and
    belong to this database (or its child data sources).
    """
    # First, discover child data source IDs from the error response
    result, status = notion_request("POST", f"/databases/{database_id}/query", {"page_size": 1})
    child_ds_ids = set()
    if status == 400:
        child_ds_ids = set(
            result.get("additional_data", {}).get("child_data_source_ids", [])
        )
    valid_parents = {database_id} | child_ds_ids

    print(f"  Database: {database_id}")
    print(f"  Child data sources: {child_ds_ids or 'none'}")
    print(f"  Scanning all pages via search API...")

    trashed = []
    has_more = True
    start_cursor = None
    total_checked = 0

    while has_more:
        body = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor

        result, status = notion_request("POST", "/search", body)
        if status != 200:
            print(f"  Search API error {status}: {json.dumps(result)[:200]}")
            break

        for page in result.get("results", []):
            if page.get("object") != "page":
                continue
            if not page.get("in_trash", False):
                continue
            parent_db = page.get("parent", {}).get("database_id", "")
            if parent_db in valid_parents:
                trashed.append(page)

        total_checked += len(result.get("results", []))
        has_more = result.get("has_more", False)
        start_cursor = result.get("next_cursor")

        if total_checked % 500 == 0:
            print(f"    Scanned {total_checked} objects, found {len(trashed)} trashed so far...")

    print(f"  Scanned {total_checked} objects total. Found {len(trashed)} trashed pages.")
    return trashed


def resolve_user_name(user_id: str, cache: dict) -> str:
    """Resolve a user ID to a display name, with caching."""
    if user_id in cache:
        return cache[user_id]
    result, status = notion_request("GET", f"/users/{user_id}")
    name = result.get("name", user_id) if status == 200 else user_id
    cache[user_id] = name
    return name


def get_page_title(page: dict) -> str:
    """Extract the title from a page's properties."""
    for prop_value in page.get("properties", {}).values():
        if prop_value.get("type") == "title":
            parts = prop_value.get("title", [])
            return "".join(t.get("plain_text", "") for t in parts) or "(Untitled)"
    return "(Untitled)"


def filter_pages(pages: list[dict], target_user: str, target_date: date) -> list[dict]:
    """Filter pages by last-edited date (IST) and editor name."""
    matched = []
    user_cache: dict[str, str] = {}

    for page in pages:
        last_edited = page.get("last_edited_time", "")
        if not last_edited:
            continue
        edited_dt = datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
        edited_date_ist = edited_dt.astimezone(IST).date()

        if edited_date_ist != target_date:
            continue

        editor = page.get("last_edited_by", {})
        editor_id = editor.get("id", "")
        editor_name = editor.get("name")

        if not editor_name and editor_id:
            editor_name = resolve_user_name(editor_id, user_cache)

        title = get_page_title(page)
        print(f"  Trashed today: \"{title}\" | by: {editor_name} | {last_edited}")

        if editor_name and target_user.lower() in editor_name.lower():
            matched.append(page)

    return matched


def restore_pages(pages: list[dict]) -> tuple[int, int]:
    """Restore pages from trash. Returns (success_count, fail_count)."""
    ok = 0
    fail = 0
    for page in pages:
        title = get_page_title(page)
        result, status = notion_request("PATCH", f"/pages/{page['id']}", {"in_trash": False})
        if status == 200:
            print(f"  [OK] Restored: \"{title}\"")
            ok += 1
        else:
            print(f"  [FAIL] \"{title}\" -- {json.dumps(result)[:200]}")
            fail += 1
    return ok, fail


# --- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Restore trashed pages from the AI Sprint Notion database."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview pages without restoring.")
    parser.add_argument("--user", type=str, default="Akash Markad",
                        help="Name of the user who deleted the pages (default: Akash Markad).")
    parser.add_argument("--date", type=str, default=None,
                        help="Date to filter (YYYY-MM-DD). Defaults to today (IST).")

    args = parser.parse_args()
    target_date = date.fromisoformat(args.date) if args.date else datetime.now(IST).date()

    print("=" * 60)
    print("  Notion Trash Restore -- AI Sprint Database")
    print(f"  Target user : {args.user}")
    print(f"  Target date : {target_date} (IST)")
    print(f"  Mode        : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)
    print()

    # Step 1: Find all trashed pages
    print("[1/4] Finding trashed pages...")
    trashed = find_all_trashed_pages(DATABASE_ID)
    if not trashed:
        print("  No trashed pages found.")
        return
    print()

    # Step 2: Filter
    print(f"[2/4] Filtering for {target_date} by \"{args.user}\"...")
    matched = filter_pages(trashed, args.user, target_date)
    print(f"\n  Matched: {len(matched)} page(s)")
    print()

    if not matched:
        print("Nothing to restore.")
        return

    # Step 3: List
    print("-" * 60)
    print("Pages to restore:")
    print("-" * 60)
    for i, page in enumerate(matched, 1):
        print(f"  {i}. {get_page_title(page)}  (ID: {page['id']})")
    print("-" * 60)
    print()

    # Step 4: Restore
    if args.dry_run:
        print("[DONE] DRY RUN complete. No pages were modified.")
        return

    print(f"[3/4] Restoring {len(matched)} page(s)...")
    ok, fail = restore_pages(matched)
    print()
    print("=" * 60)
    print(f"  Done! Restored: {ok} | Failed: {fail}")
    print("=" * 60)


if __name__ == "__main__":
    main()
