# Archived one-off scripts

These scripts were written for specific past incidents (hardcoded batch IDs,
screenshot-derived CMS IDs, `D:\` Windows paths, one-time migrations). None of
them are imported or invoked by the dashboard, the pipeline, or any launcher —
verified by grepping every `.py`, `.bat`, `.sh`, and template.

They are kept for reference. If you need one again, check its hardcoded values
first — they almost certainly refer to a past state of the data.

- `root/` — scripts that lived in the repo root
- `pipeline/` — scripts that lived in `pipeline/`
  - `retry_notion_failed.py` was an exact duplicate of `pipeline/retry_failed_notion.py`
    (differing only in the Notion status filter) — use that one instead.
