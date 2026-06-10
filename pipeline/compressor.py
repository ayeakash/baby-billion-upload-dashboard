"""
compressor.py — FFmpeg-based video compressor for the BabyBillion pipeline.

Goal: ensure every MP4 is under TARGET_MB before batching.

Strategy:
  1. If the file is already under TARGET_MB → skip (return as-is)
  2. Calculate a target bitrate from the video duration to hit ~(TARGET_MB - 1 MB) headroom
     target_bitrate_kbps = (TARGET_MB_BYTES - AUDIO_BYTES) * 8 / duration_s / 1000
  3. Encode with ffmpeg: H.264 (libx264) + AAC 128k, scale to ≤1280px wide
  4. If the result is still too large (rare edge case): re-encode at CRF 32 as fallback
  5. Overwrites the original file in-place (compressor is non-destructive to the pipeline)

Usage:
    import compressor
    compressed_path = compressor.compress(page_id, video_name, local_file)
    # Returns the path to the (possibly compressed) file, or None on hard failure
"""
from __future__ import annotations

import os
import subprocess
import logging
import shutil

log = logging.getLogger(__name__)

# ── Settings ──────────────────────────────────────────────────────────────────
TARGET_MB        = 20          # hard ceiling in MB
TARGET_BYTES     = TARGET_MB * 1024 * 1024
HEADROOM_BYTES   = 1.5 * 1024 * 1024   # 1.5 MB safety margin
AUDIO_KBPS       = 128                  # AAC audio bitrate
MAX_WIDTH        = 1280                 # cap at 720p-ish width


def _get_duration(path: str) -> float | None:
    """Return video duration in seconds via ffprobe, or None on failure."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=30)
        return float(out.strip())
    except Exception as e:
        log.warning(f"  ffprobe failed for {path}: {e}")
        return None


def _encode(src: str, dst: str, video_kbps: int) -> bool:
    """
    Single-pass encode: libx264 at video_kbps, AAC at AUDIO_KBPS.
    Scale to MAX_WIDTH if wider. Returns True on success.
    """
    vf = f"scale='min({MAX_WIDTH},iw)':-2"   # keep aspect ratio
    cmd = [
        "ffmpeg", "-y",
        "-i", src,
        "-vcodec", "libx264",
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{int(video_kbps * 1.2)}k",
        "-bufsize", f"{video_kbps * 2}k",
        "-vf", vf,
        "-acodec", "aac",
        "-b:a", f"{AUDIO_KBPS}k",
        "-movflags", "+faststart",
        dst,
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=600,    # 10-min max per video
        )
        if result.returncode != 0:
            log.warning(f"  ffmpeg stderr: {result.stderr[-500:].decode(errors='replace')}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log.error(f"  ffmpeg timed out on {src}")
        return False
    except Exception as e:
        log.error(f"  ffmpeg error: {e}")
        return False


def compress(page_id: str, video_name: str, local_file: str) -> str | None:
    """
    Compress local_file to under TARGET_MB if needed.
    Returns the path to the final file (may be the original if skipped).
    Returns None if compression hard-fails and original is unusable.
    """
    if not os.path.isfile(local_file):
        log.error(f"  [COMPRESS] File not found: {local_file}")
        return None

    file_size = os.path.getsize(local_file)
    size_mb = file_size / (1024 * 1024)

    if file_size <= TARGET_BYTES:
        log.info(f"  [COMPRESS] {video_name}: {size_mb:.1f} MB — under {TARGET_MB} MB, skip")
        return local_file

    log.info(f"  [COMPRESS] {video_name}: {size_mb:.1f} MB — compressing to <{TARGET_MB} MB ...")

    # ── Get duration ──────────────────────────────────────────────────────────
    duration = _get_duration(local_file)
    if not duration or duration <= 0:
        log.error(f"  [COMPRESS] Cannot determine duration for {video_name}")
        return local_file   # pass through rather than block

    # ── Calculate target video bitrate ────────────────────────────────────────
    target_total_bytes = TARGET_BYTES - HEADROOM_BYTES
    audio_bytes = (AUDIO_KBPS * 1000 / 8) * duration
    video_bytes = target_total_bytes - audio_bytes
    video_kbps  = max(200, int(video_bytes * 8 / duration / 1000))

    log.info(f"    Duration: {duration:.1f}s | Target video bitrate: {video_kbps} kbps")

    # ── Encode to a temp file ─────────────────────────────────────────────────
    base, ext = os.path.splitext(local_file)
    tmp_file  = f"{base}_compressed{ext}"

    ok = _encode(local_file, tmp_file, video_kbps)

    if not ok or not os.path.isfile(tmp_file):
        log.error(f"  [COMPRESS] Encoding failed for {video_name} — using original")
        if os.path.isfile(tmp_file):
            os.remove(tmp_file)
        return local_file

    result_size    = os.path.getsize(tmp_file)
    result_size_mb = result_size / (1024 * 1024)

    if result_size > TARGET_BYTES:
        # Fallback: try again at CRF 32 fixed quality
        log.warning(
            f"  [COMPRESS] Still {result_size_mb:.1f} MB after bitrate pass — "
            f"trying CRF 32 fallback ..."
        )
        os.remove(tmp_file)
        crf_cmd = [
            "ffmpeg", "-y",
            "-i", local_file,
            "-vcodec", "libx264", "-crf", "32",
            "-vf", f"scale='min({MAX_WIDTH},iw)':-2",
            "-acodec", "aac", "-b:a", f"{AUDIO_KBPS}k",
            "-movflags", "+faststart",
            tmp_file,
        ]
        try:
            subprocess.run(crf_cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=600)
        except Exception:
            pass

        if os.path.isfile(tmp_file):
            result_size    = os.path.getsize(tmp_file)
            result_size_mb = result_size / (1024 * 1024)
            log.info(f"    CRF 32 result: {result_size_mb:.1f} MB")
        else:
            log.error(f"  [COMPRESS] CRF fallback also failed — using original")
            return local_file

    # ── Replace original with compressed ─────────────────────────────────────
    os.replace(tmp_file, local_file)
    log.info(
        f"  [COMPRESS] {video_name}: {size_mb:.1f} MB → {result_size_mb:.1f} MB "
        f"({'OK' if result_size <= TARGET_BYTES else 'WARN: still over limit'})"
    )
    return local_file


def compress_all(videos: list[dict]) -> list[dict]:
    """
    Compress all downloaded videos in the list.
    Updates v['local_file'] in-place (path doesn't change, but file is smaller).
    Returns the same list for chaining.
    """
    total = len(videos)
    for i, v in enumerate(videos, 1):
        local_file = v.get("local_file", "")
        if not local_file:
            continue
        log.info(f"\n  Compressing [{i}/{total}]: {v['video_name']}")
        result = compress(v["page_id"] + v.get("lang_suffix", ""), v["video_name"], local_file)
        if result:
            v["local_file"] = result
    return videos
