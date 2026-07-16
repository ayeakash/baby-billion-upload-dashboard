"""
compressor.py — FFmpeg-based video compressor for the BabyBillion pipeline.

Goal: ensure every MP4 is under TARGET_MB before batching.

Strategy (multi-pass, increasingly aggressive):
  1. If the file is already under TARGET_MB → skip (return as-is)
  2. Pass 1: Two-pass ABR encoding targeting exact file size
  3. Pass 2: If still over, CRF 30 + scale to 720p
  4. Pass 3: If still over, CRF 35 + scale to 480p + lower audio
  5. Pass 4: If still over, CRF 40 + scale to 360p (nuclear option)

Uses ffmpeg with libx264. On macOS, uses VideoToolbox for probe speed.
"""
from __future__ import annotations

import os
import subprocess
import logging
import shutil

log = logging.getLogger(__name__)

# ── Settings ──────────────────────────────────────────────────────────────────
HEADROOM_BYTES   = 1.5 * 1024 * 1024   # 1.5 MB safety margin
AUDIO_KBPS       = 128                  # AAC audio bitrate
MAX_WIDTH        = 1280                 # cap at 720p-ish width


def _get_target_mb() -> int:
    """Target per-video size: half the batch limit, capped at [5, 20] MB."""
    try:
        from config import MAX_BATCH_BYTES
        return min(20, max(5, int(MAX_BATCH_BYTES / (1024 * 1024) / 2)))
    except ImportError:
        return 15


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


def _get_resolution(path: str) -> tuple[int, int] | None:
    """Return (width, height) of the video."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        path,
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=30)
        parts = out.strip().decode().split("x")
        return int(parts[0]), int(parts[1])
    except Exception:
        return None


def _run_ffmpeg(cmd: list[str], timeout: int = 900) -> bool:
    """Run an ffmpeg command, return True on success."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr[-500:].decode(errors='replace')
            log.warning(f"  ffmpeg stderr: {stderr}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log.error(f"  ffmpeg timed out ({timeout}s)")
        return False
    except Exception as e:
        log.error(f"  ffmpeg error: {e}")
        return False


def _encode_two_pass(src: str, dst: str, video_kbps: int,
                     max_width: int = 1280, audio_kbps: int = 128) -> bool:
    """
    Two-pass ABR encoding for precise file size control.
    Pass 1: analysis only (writes stats to /dev/null).
    Pass 2: actual encode with target bitrate.
    """
    vf = f"scale='min({max_width},iw)':-2"

    # Pass 1
    pass1_cmd = [
        "ffmpeg", "-y",
        "-i", src,
        "-vcodec", "libx264",
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{int(video_kbps * 1.5)}k",
        "-bufsize", f"{video_kbps * 2}k",
        "-preset", "medium",
        "-vf", vf,
        "-pass", "1",
        "-passlogfile", dst + "_passlog",
        "-an",
        "-f", "null",
        "/dev/null",
    ]

    log.info(f"    Two-pass encode: {video_kbps} kbps, max_width={max_width}")
    if not _run_ffmpeg(pass1_cmd):
        log.warning("    Pass 1 failed, falling back to single-pass")
        return _encode_single(src, dst, video_kbps, max_width, audio_kbps)

    # Pass 2
    pass2_cmd = [
        "ffmpeg", "-y",
        "-i", src,
        "-vcodec", "libx264",
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{int(video_kbps * 1.5)}k",
        "-bufsize", f"{video_kbps * 2}k",
        "-preset", "medium",
        "-vf", vf,
        "-pass", "2",
        "-passlogfile", dst + "_passlog",
        "-acodec", "aac",
        "-b:a", f"{audio_kbps}k",
        "-movflags", "+faststart",
        dst,
    ]

    ok = _run_ffmpeg(pass2_cmd)

    # Clean up passlog files
    for suffix in ("-0.log", "-0.log.mbtree", "_passlog-0.log", "_passlog-0.log.mbtree"):
        path = dst + suffix
        if os.path.isfile(path):
            os.remove(path)

    return ok


def _encode_single(src: str, dst: str, video_kbps: int,
                    max_width: int = 1280, audio_kbps: int = 128) -> bool:
    """Single-pass ABR encode."""
    vf = f"scale='min({max_width},iw)':-2"
    cmd = [
        "ffmpeg", "-y",
        "-i", src,
        "-vcodec", "libx264",
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{int(video_kbps * 1.5)}k",
        "-bufsize", f"{video_kbps * 2}k",
        "-preset", "medium",
        "-vf", vf,
        "-acodec", "aac",
        "-b:a", f"{audio_kbps}k",
        "-movflags", "+faststart",
        dst,
    ]
    return _run_ffmpeg(cmd)


def _encode_crf(src: str, dst: str, crf: int,
                max_width: int = 1280, audio_kbps: int = 128,
                preset: str = "medium") -> bool:
    """CRF-based encode (quality-target, not size-target)."""
    vf = f"scale='min({max_width},iw)':-2"
    cmd = [
        "ffmpeg", "-y",
        "-i", src,
        "-vcodec", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-vf", vf,
        "-acodec", "aac",
        "-b:a", f"{audio_kbps}k",
        "-movflags", "+faststart",
        dst,
    ]
    return _run_ffmpeg(cmd)


def compress(page_id: str, video_name: str, local_file: str) -> str | None:
    """
    Compress local_file to fit within the batch size limit if needed.
    Uses increasingly aggressive strategies until the file is under target.

    Returns the path to the final file, or None if compression hard-fails.
    """
    TARGET_MB    = _get_target_mb()
    TARGET_BYTES = TARGET_MB * 1024 * 1024

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

    resolution = _get_resolution(local_file)
    if resolution:
        log.info(f"    Source: {resolution[0]}x{resolution[1]}, {duration:.1f}s, {size_mb:.1f} MB")

    # ── Temp file ─────────────────────────────────────────────────────────────
    base, ext = os.path.splitext(local_file)
    tmp_file  = f"{base}_compressed{ext}"

    # ── Define compression passes (increasingly aggressive) ───────────────────
    passes = []

    # Pass 1: Two-pass ABR at calculated bitrate, 720p max
    target_bytes = TARGET_BYTES - HEADROOM_BYTES
    audio_bytes = (AUDIO_KBPS * 1000 / 8) * duration
    video_bytes = max(0, target_bytes - audio_bytes)
    video_kbps  = max(150, int(video_bytes * 8 / duration / 1000))

    passes.append({
        "name": "Two-pass ABR",
        "fn": lambda: _encode_two_pass(local_file, tmp_file, video_kbps,
                                        max_width=1280, audio_kbps=128),
    })

    # Pass 2: CRF 28 + 720p (good quality, smaller)
    passes.append({
        "name": "CRF 28 + 720p",
        "fn": lambda: _encode_crf(local_file, tmp_file, crf=28,
                                   max_width=1280, audio_kbps=96),
    })

    # Pass 3: CRF 32 + 480p + lower audio (aggressive)
    passes.append({
        "name": "CRF 32 + 480p",
        "fn": lambda: _encode_crf(local_file, tmp_file, crf=32,
                                   max_width=854, audio_kbps=64),
    })

    # Pass 4: CRF 36 + 360p (very aggressive)
    passes.append({
        "name": "CRF 36 + 360p",
        "fn": lambda: _encode_crf(local_file, tmp_file, crf=36,
                                   max_width=640, audio_kbps=48, preset="fast"),
    })

    # Pass 5: CRF 42 + 240p (nuclear option — should always work)
    passes.append({
        "name": "CRF 42 + 240p (nuclear)",
        "fn": lambda: _encode_crf(local_file, tmp_file, crf=42,
                                   max_width=426, audio_kbps=32, preset="fast"),
    })

    # ── Run passes until file is under target ─────────────────────────────────
    for i, p in enumerate(passes):
        log.info(f"    Pass {i+1}/{len(passes)}: {p['name']}...")

        # Clean up any previous temp file
        if os.path.isfile(tmp_file):
            os.remove(tmp_file)

        ok = p["fn"]()

        if not ok or not os.path.isfile(tmp_file):
            log.warning(f"    Pass {i+1} encode failed — trying next")
            continue

        result_size = os.path.getsize(tmp_file)
        result_mb = result_size / (1024 * 1024)

        if result_size <= TARGET_BYTES:
            # Success!
            os.replace(tmp_file, local_file)
            log.info(
                f"  [COMPRESS] ✅ {video_name}: {size_mb:.1f} MB → {result_mb:.1f} MB "
                f"(pass {i+1}: {p['name']})"
            )
            return local_file
        else:
            log.warning(
                f"    Pass {i+1} result: {result_mb:.1f} MB — still over {TARGET_MB} MB"
            )

    # ── All passes exhausted ──────────────────────────────────────────────────
    # Use whatever the last pass produced (even if over target)
    if os.path.isfile(tmp_file):
        result_size = os.path.getsize(tmp_file)
        result_mb = result_size / (1024 * 1024)

        if result_size < file_size:
            # At least it's smaller than the original
            os.replace(tmp_file, local_file)
            log.warning(
                f"  [COMPRESS] ⚠️ {video_name}: {size_mb:.1f} MB → {result_mb:.1f} MB "
                f"(still over {TARGET_MB} MB but using compressed version)"
            )
            return local_file
        else:
            os.remove(tmp_file)

    log.error(f"  [COMPRESS] ❌ {video_name}: all passes failed — using original ({size_mb:.1f} MB)")
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
