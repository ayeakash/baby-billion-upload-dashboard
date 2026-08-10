"""
social_media_downloader.py -- Download videos from YouTube and Instagram.

Handles:
  - Single video/reel downloads from YouTube and Instagram
  - Batch downloads from YouTube channels
  - Batch downloads from Instagram accounts
"""
from __future__ import annotations

import os
import re
import logging
import yt_dlp
from config import DOWNLOADS_DIR

log = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Turn a title into a safe filename."""
    name = re.sub(r'[^\w\s\-]', '', name)
    name = re.sub(r'[\s]+', '_', name.strip())
    return name[:100]


def normalize_youtube_url(url: str) -> str:
    """
    Convert various YouTube URL formats to standard watch URL.
    Handles: shorts, youtu.be, various YouTube domains, etc.
    """
    # Extract video ID
    video_id = None

    # Handle YouTube Shorts: youtube.com/shorts/VIDEOID
    if '/shorts/' in url:
        match = re.search(r'/shorts/([a-zA-Z0-9_-]{11})', url)
        if match:
            video_id = match.group(1)

    # Handle standard watch URL: youtube.com/watch?v=VIDEOID
    elif 'watch?v=' in url:
        match = re.search(r'v=([a-zA-Z0-9_-]{11})', url)
        if match:
            video_id = match.group(1)

    # Handle youtu.be: youtu.be/VIDEOID
    elif 'youtu.be/' in url:
        match = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', url)
        if match:
            video_id = match.group(1)

    # If we extracted a video ID, return standard format
    if video_id:
        return f'https://www.youtube.com/watch?v={video_id}'

    # Otherwise return original URL
    return url


def download_youtube_video(video_url: str, video_title: str = None) -> str | None:
    """
    Download a single YouTube video.
    Returns the absolute local file path on success, None on failure.
    Handles YouTube Shorts, standard videos, youtu.be links, etc.
    """
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    if not video_title:
        video_title = "YouTube_Video"

    # Normalize URL (convert Shorts to watch URL, etc.)
    normalized_url = normalize_youtube_url(video_url)
    if normalized_url != video_url:
        log.info(f"  [INFO] Converted Shorts URL to: {normalized_url}")
        video_url = normalized_url

    safe_name = sanitize_filename(video_title)
    out_path = os.path.join(DOWNLOADS_DIR, f"{safe_name}.mp4")

    # Already downloaded?
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 10_000:
        log.info(f"  [SKIP]  Already downloaded: {os.path.basename(out_path)}")
        return out_path

    log.info(f"  [DOWN]  Downloading YouTube video: {video_title}")
    log.info(f"     Original link: {video_url}")

    try:
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': out_path.replace('.mp4', ''),
            'quiet': False,
            'no_warnings': False,
            'no_check_certificate': True,
            'socket_timeout': 30,
            'verbose': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            log.info(f"  [INFO] Downloading with yt-dlp...")
            info = ydl.extract_info(video_url, download=True)
            filename = ydl.prepare_filename(info)

        # Ensure .mp4 extension
        if filename and not filename.lower().endswith('.mp4'):
            final_path = filename + '.mp4' if not filename.endswith('.') else filename[:-1] + '.mp4'
            if os.path.isfile(filename):
                os.rename(filename, final_path)
                filename = final_path

        if os.path.isfile(filename) and os.path.getsize(filename) > 10_000:
            size_mb = os.path.getsize(filename) / 1024 / 1024
            log.info(f"  [OK] Downloaded: {os.path.basename(filename)} ({size_mb:.1f} MB)")
            return filename
        else:
            log.error(f"  [FAIL] Download resulted in invalid file")
            return None

    except Exception as e:
        log.error(f"  [FAIL] Download failed for '{video_title}': {type(e).__name__}: {e}")
        import traceback
        log.error(f"  [TRACEBACK] {traceback.format_exc()}")
        return None


def download_instagram_post(post_url: str, post_title: str = None) -> str | None:
    """
    Download a single Instagram post/reel.
    Returns the absolute local file path on success, None on failure.
    """
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    if not post_title:
        post_title = "Instagram_Post"

    safe_name = sanitize_filename(post_title)
    out_path = os.path.join(DOWNLOADS_DIR, f"{safe_name}.mp4")

    # Already downloaded?
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 10_000:
        log.info(f"  [SKIP]  Already downloaded: {os.path.basename(out_path)}")
        return out_path

    log.info(f"  [DOWN]  Downloading Instagram post: {post_title}")
    log.info(f"     Link: {post_url}")

    try:
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': out_path.replace('.mp4', ''),
            'quiet': False,
            'no_warnings': False,
            'no_check_certificate': True,
            'socket_timeout': 30,
            'verbose': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            log.info(f"  [INFO] Downloading with yt-dlp...")
            info = ydl.extract_info(post_url, download=True)
            filename = ydl.prepare_filename(info)

        # Ensure .mp4 extension
        if filename and not filename.lower().endswith('.mp4'):
            final_path = filename + '.mp4' if not filename.endswith('.') else filename[:-1] + '.mp4'
            if os.path.isfile(filename):
                os.rename(filename, final_path)
                filename = final_path

        if os.path.isfile(filename) and os.path.getsize(filename) > 10_000:
            size_mb = os.path.getsize(filename) / 1024 / 1024
            log.info(f"  [OK] Downloaded: {os.path.basename(filename)} ({size_mb:.1f} MB)")
            return filename
        else:
            log.error(f"  [FAIL] Download resulted in invalid file")
            return None

    except Exception as e:
        log.error(f"  [FAIL] Download failed for '{post_title}': {type(e).__name__}: {e}")
        import traceback
        log.error(f"  [TRACEBACK] {traceback.format_exc()}")
        return None


def download_youtube_channel(channel_url: str, max_videos: int = 50) -> list[str]:
    """
    Download all videos from a YouTube channel.
    Returns a list of downloaded file paths.
    """
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    downloaded_files = []

    log.info(f"  [CHANNEL] Downloading videos from YouTube channel")
    log.info(f"     Link: {channel_url}")
    log.info(f"     Max videos: {max_videos}")

    try:
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': os.path.join(DOWNLOADS_DIR, '%(title)s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            'playlistend': max_videos,
            'no_check_certificate': True,
            'socket_timeout': 30,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=True)

            # Handle both single video and playlist cases
            if 'entries' in info:
                for entry in info['entries']:
                    if entry:
                        filename = ydl.prepare_filename(entry)
                        # Ensure .mp4 extension
                        if filename and not filename.lower().endswith('.mp4'):
                            final_path = filename + '.mp4' if not filename.endswith('.') else filename[:-1] + '.mp4'
                            if os.path.isfile(filename):
                                os.rename(filename, final_path)
                                filename = final_path
                        if os.path.isfile(filename):
                            downloaded_files.append(filename)
                            size_mb = os.path.getsize(filename) / 1024 / 1024
                            log.info(f"  [OK] Downloaded: {os.path.basename(filename)} ({size_mb:.1f} MB)")
            else:
                filename = ydl.prepare_filename(info)
                # Ensure .mp4 extension
                if filename and not filename.lower().endswith('.mp4'):
                    final_path = filename + '.mp4' if not filename.endswith('.') else filename[:-1] + '.mp4'
                    if os.path.isfile(filename):
                        os.rename(filename, final_path)
                        filename = final_path
                if os.path.isfile(filename):
                    downloaded_files.append(filename)
                    size_mb = os.path.getsize(filename) / 1024 / 1024
                    log.info(f"  [OK] Downloaded: {os.path.basename(filename)} ({size_mb:.1f} MB)")

        log.info(f"  [CHANNEL] Total downloaded: {len(downloaded_files)} videos")
        return downloaded_files

    except Exception as e:
        log.error(f"  [FAIL] Channel download failed: {e}", exc_info=True)
        return downloaded_files


def download_instagram_account(account_url: str, max_posts: int = 50) -> list[str]:
    """
    Download all videos/reels from an Instagram account.
    Returns a list of downloaded file paths.
    """
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    downloaded_files = []

    log.info(f"  [ACCOUNT] Downloading posts from Instagram account")
    log.info(f"     Link: {account_url}")
    log.info(f"     Max posts: {max_posts}")

    try:
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': os.path.join(DOWNLOADS_DIR, '%(title)s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            'playlistend': max_posts,
            'no_check_certificate': True,
            'socket_timeout': 30,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(account_url, download=True)

            # Handle both single post and account (multiple posts) cases
            if 'entries' in info:
                for entry in info['entries']:
                    if entry:
                        try:
                            filename = ydl.prepare_filename(entry)
                            # Ensure .mp4 extension
                            if filename and not filename.lower().endswith('.mp4'):
                                final_path = filename + '.mp4' if not filename.endswith('.') else filename[:-1] + '.mp4'
                                if os.path.isfile(filename):
                                    os.rename(filename, final_path)
                                    filename = final_path
                            if os.path.isfile(filename) and os.path.getsize(filename) > 10_000:
                                downloaded_files.append(filename)
                                size_mb = os.path.getsize(filename) / 1024 / 1024
                                log.info(f"  [OK] Downloaded: {os.path.basename(filename)} ({size_mb:.1f} MB)")
                        except Exception as e:
                            log.warning(f"  [WARN] Failed to process entry: {e}")
            else:
                filename = ydl.prepare_filename(info)
                # Ensure .mp4 extension
                if filename and not filename.lower().endswith('.mp4'):
                    final_path = filename + '.mp4' if not filename.endswith('.') else filename[:-1] + '.mp4'
                    if os.path.isfile(filename):
                        os.rename(filename, final_path)
                        filename = final_path
                if os.path.isfile(filename) and os.path.getsize(filename) > 10_000:
                    downloaded_files.append(filename)
                    size_mb = os.path.getsize(filename) / 1024 / 1024
                    log.info(f"  [OK] Downloaded: {os.path.basename(filename)} ({size_mb:.1f} MB)")

        log.info(f"  [ACCOUNT] Total downloaded: {len(downloaded_files)} videos")
        return downloaded_files

    except Exception as e:
        log.error(f"  [FAIL] Account download failed: {e}", exc_info=True)
        return downloaded_files
