"""
downloader.py -- Download videos from Google Drive links.

Handles:
  - Direct file links:   drive.google.com/file/d/{FILE_ID}/view
  - Folder links:        drive.google.com/drive/folders/{FOLDER_ID}
  - Short drive links:   drive.google.com/open?id={FILE_ID}

Folder download strategy (handles nested subfolders):
  1. Download entire folder to a temp dir via gdown.download_folder
  2. Search for a 'render' subfolder (case-insensitive) -> use MP4s from there FIRST
  3. If no render subfolder (or it has no MP4s), use any MP4 found anywhere
  4. Pick the LARGEST MP4 (to avoid preview thumbnails or audio-only exports)
  5. Move chosen file to out_path, clean up temp dir

Uses gdown (pip install gdown) which handles auth cookies and
large-file download confirmations automatically.
"""
from __future__ import annotations

import os
import re
import shutil
import logging
import unicodedata
import gdown
from config import DOWNLOADS_DIR

log = logging.getLogger(__name__)

# Subfolder names that indicate the final render -- checked case-insensitively
RENDER_FOLDER_NAMES = {"render", "renders", "final", "final render", "final_render", "output"}


# ── Filename helpers ───────────────────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    """
    Turn a video title into a safe filename (no spaces or special chars).
    Example: "Letter A (Apple, Ant)" -> "Letter_A_Apple_Ant"
    """
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^\w\s\-]", "", name)
    name = re.sub(r"[\s]+", "_", name.strip())
    return name[:100]


# ── Link parsers ───────────────────────────────────────────────────────────────

def _extract_file_id(url: str) -> str | None:
    """Extract Google Drive FILE ID from various link formats."""
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]{10,})",
        r"id=([a-zA-Z0-9_-]{10,})",
        r"/open\?id=([a-zA-Z0-9_-]{10,})",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _extract_folder_id(url: str) -> str | None:
    """
    Extract Google Drive FOLDER ID from folder links.
    Handles /drive/folders/ and /drive/u/N/folders/ formats.
    """
    m = re.search(r"/drive(?:/u/\d+)?/folders/([a-zA-Z0-9_-]{10,})", url)
    return m.group(1) if m else None


def _is_folder_link(url: str) -> bool:
    return "/drive/folders/" in url or (("/drive/u/" in url) and ("/folders/" in url))


# ── MP4 search helpers ────────────────────────────────────────────────────────

def _walk_mp4s(root_dir: str) -> list[str]:
    """Recursively find all MP4 files under root_dir."""
    results = []
    for dirpath, _dirs, filenames in os.walk(root_dir):
        for fname in filenames:
            if fname.lower().endswith(".mp4"):
                results.append(os.path.join(dirpath, fname))
    return results


def _is_in_render_folder(filepath: str, root_dir: str) -> bool:
    """
    Returns True if any directory component between root_dir and the file
    matches one of RENDER_FOLDER_NAMES (case-insensitive).

    Examples that return True:
      root/Render/video.mp4
      root/ProjectName/Final/video.mp4
      root/ProjectName/Output/video.mp4
      root/ProjectName/Final_Render/video.mp4
    """
    rel   = os.path.relpath(filepath, root_dir)
    parts = rel.split(os.sep)
    # Check all parts EXCEPT the last element (the filename itself)
    for part in parts[:-1]:
        if part.strip().lower() in RENDER_FOLDER_NAMES:
            return True
    return False


def _pick_best_mp4(mp4_list: list[str]) -> str:
    """Return the largest MP4 (avoids thumbnails / audio-only previews)."""
    return max(mp4_list, key=lambda p: os.path.getsize(p))


def _log_found(tmp_dir: str, all_mp4s: list, render_mp4s: list) -> None:
    """Log a clear tree of what was found in the downloaded folder."""
    log.info(f"  Found {len(all_mp4s)} MP4(s) total:")
    for p in sorted(all_mp4s):
        rel  = os.path.relpath(p, tmp_dir)
        size = os.path.getsize(p) / 1024 / 1024
        tag  = "[RENDER] [RENDER]" if p in render_mp4s else "   [other] "
        log.info(f"      {tag}  {rel}  ({size:.1f} MB)")


# ── Main public API ────────────────────────────────────────────────────────────

def download_video(page_id: str, video_name: str, drive_link: str) -> str | None:
    """
    Download a video from Google Drive to DOWNLOADS_DIR.
    Returns the absolute local file path on success, None on failure.
    """
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    safe_name = sanitize_filename(video_name)
    out_path  = os.path.join(DOWNLOADS_DIR, f"{safe_name}.mp4")

    # Already downloaded?
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 10_000:
        log.info(f"  [SKIP]  Already downloaded: {os.path.basename(out_path)}")
        return out_path

    log.info(f"  [DOWN]  Downloading: {video_name}")
    log.info(f"     Link: {drive_link}")

    try:
        if _is_folder_link(drive_link):
            return _download_from_folder(drive_link, safe_name, out_path)
        else:
            return _download_file(drive_link, out_path)
    except Exception as e:
        log.error(f"  [FAIL] Download failed for '{video_name}': {e}")
        return None


# ── Direct file download ───────────────────────────────────────────────────────

def _download_file(drive_link: str, out_path: str) -> str | None:
    """Download a direct Google Drive file link."""
    file_id = _extract_file_id(drive_link)
    if not file_id:
        log.error(f"  Could not extract file ID from: {drive_link}")
        return None

    url    = f"https://drive.google.com/uc?id={file_id}"
    result = gdown.download(url, out_path, quiet=False)

    if result and os.path.isfile(result) and os.path.getsize(result) > 10_000:
        size_mb = os.path.getsize(result) / 1024 / 1024
        log.info(f"  [OK] Downloaded: {os.path.basename(result)} ({size_mb:.1f} MB)")
        return result

    log.error(f"  [FAIL] gdown returned no usable file (result={result})")
    return None


# ── Folder download (with render-subfolder priority) ──────────────────────────

def _download_from_folder(folder_link: str, safe_name: str, out_path: str) -> str | None:
    """
    Download the best video from a Google Drive folder link.

    Selection priority:
      1. MP4s inside a 'render' / 'renders' / 'final' / 'output' subfolder
         (matched case-insensitively anywhere in the path)
      2. Any other MP4 anywhere in the folder tree (fallback)
      In both cases: prefer the LARGEST file.

    Steps:
      a. Download the entire folder tree to a temp directory
      b. Walk tree -> find all MP4s -> split into render vs other
      c. Pick the best, move to out_path, clean up temp dir
    """
    folder_id = _extract_folder_id(folder_link)
    if not folder_id:
        log.error(f"  Could not extract folder ID from: {folder_link}")
        return None

    tmp_dir = os.path.join(DOWNLOADS_DIR, f"_tmp_{folder_id}_{safe_name[:20]}")
    os.makedirs(tmp_dir, exist_ok=True)

    log.info(f"  [FOLDER] Folder link detected (folder ID: {folder_id})")
    log.info(f"     Downloading full folder -> {tmp_dir}")
    log.info(f"     Render subfolders recognised: {sorted(RENDER_FOLDER_NAMES)}")

    try:
        gdown.download_folder(
            url=f"https://drive.google.com/drive/folders/{folder_id}",
            output=tmp_dir,
            quiet=False,
            use_cookies=False,
        )
    except Exception as e:
        # Partial downloads are still usable
        log.warning(f"  [WARN]  gdown.download_folder raised: {e} -- continuing with partial download")

    # ── Walk the downloaded tree ───────────────────────────────────────────────
    all_mp4s    = _walk_mp4s(tmp_dir)
    render_mp4s = [p for p in all_mp4s if _is_in_render_folder(p, tmp_dir)]
    other_mp4s  = [p for p in all_mp4s if p not in render_mp4s]

    _log_found(tmp_dir, all_mp4s, render_mp4s)

    # ── Choose the best MP4 ────────────────────────────────────────────────────
    if render_mp4s:
        chosen = _pick_best_mp4(render_mp4s)
        source = "render/ subfolder"
    elif other_mp4s:
        chosen = _pick_best_mp4(other_mp4s)
        source = "folder root (no render/ subfolder found -- used largest MP4)"
    else:
        log.error(f"  [FAIL] No MP4 files found anywhere in folder {folder_id}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    size_mb = os.path.getsize(chosen) / 1024 / 1024
    rel_path = os.path.relpath(chosen, tmp_dir)
    log.info(f"  [OK] Selected [{source}]:")
    log.info(f"     {rel_path}  ({size_mb:.1f} MB)")

    # ── Move to final destination ──────────────────────────────────────────────
    shutil.move(chosen, out_path)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    final_mb = os.path.getsize(out_path) / 1024 / 1024
    log.info(f"  [OK] Saved to: {out_path} ({final_mb:.1f} MB)")
    return out_path
