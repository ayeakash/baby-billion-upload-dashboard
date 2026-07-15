"""Diagnose why ~50 videos marked 'Ready to Upload' aren't being fetched."""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pipeline'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Enable detailed logging
import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')

from pipeline import notion_client

# Run the actual query with full logging
print("=" * 80)
print("Running query_ready_to_upload() with full diagnostics...")
print("=" * 80)
results = notion_client.query_ready_to_upload()

print(f"\n{'=' * 80}")
print(f"RESULT: {len(results)} videos passed all filters")
print(f"{'=' * 80}")
for r in results:
    print(f"  {r['video_name'][:50]:50s} cat={r['category']:25s}")
