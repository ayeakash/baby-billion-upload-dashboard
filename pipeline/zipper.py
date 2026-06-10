"""
zipper.py -- Creates ZIP archives for each batch folder.

Uses ZIP_STORED (no compression) since MP4s are already compressed.
Skips batches that already have a valid ZIP.
"""
from __future__ import annotations

import os
import re
import zipfile
import logging
from config import BATCHES_DIR

log = logging.getLogger(__name__)


def zip_batch(batch_name: str) -> str | None:
    """
    Zip all MP4s in BATCHES_DIR/batch_name into BATCHES_DIR/batch_name.zip
    Returns the ZIP path on success, None if no MP4s found.
    """
    batch_folder = os.path.join(BATCHES_DIR, batch_name)
    zip_path     = os.path.join(BATCHES_DIR, f"{batch_name}.zip")

    if os.path.isfile(zip_path) and os.path.getsize(zip_path) > 1024:
        log.info(f"  [SKIP] ZIP already exists: {batch_name}.zip")
        return zip_path

    mp4_files = [
        f for f in os.listdir(batch_folder)
        if f.lower().endswith(".mp4")
    ]
    if not mp4_files:
        log.warning(f"  No MP4 files in {batch_folder} -- skipping ZIP")
        return None

    log.info(f"  [ZIP] Zipping {len(mp4_files)} files -> {batch_name}.zip …")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        for fname in mp4_files:
            full_path = os.path.join(batch_folder, fname)
            zf.write(full_path, arcname=fname)

    size_mb = os.path.getsize(zip_path) / 1024 / 1024
    log.info(f"  [OK] Created: {batch_name}.zip ({size_mb:.1f} MB)")
    return zip_path


def zip_all(batch_names: list[str]) -> dict[str, str]:
    """
    Zip a list of batches. Returns {batch_name: zip_path} for successful ones.
    """
    results = {}
    for name in batch_names:
        path = zip_batch(name)
        if path:
            results[name] = path
    return results


def discover_unzipped_batches() -> list[str]:
    """Find batch folders that don't have a zip yet."""
    if not os.path.isdir(BATCHES_DIR):
        return []
    unzipped = []
    for entry in sorted(os.listdir(BATCHES_DIR)):
        if not re.match(r"^Batch_\d+$", entry):
            continue
        folder = os.path.join(BATCHES_DIR, entry)
        if not os.path.isdir(folder):
            continue
        zip_path = os.path.join(BATCHES_DIR, f"{entry}.zip")
        if not os.path.isfile(zip_path):
            unzipped.append(entry)
    return unzipped
