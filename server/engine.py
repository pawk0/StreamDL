import gc
import logging
import os
import re
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

import yt_dlp

from server.cleanup import cleanup_task_files
from server.config import load_settings
from server.patches import apply_ytdlp_patches
from server.resolvers import is_doodstream_url, resolve_doodstream
from server.task import DownloadTask
from server.utils import (
    format_bytes,
    format_eta,
    get_unique_base,
    is_generic_title,
    sanitize_filename,
)

logger = logging.getLogger("video_dl.engine")

# Apply yt-dlp compatibility patches immediately on module load
apply_ytdlp_patches()

DEFAULT_HTTP_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Site": "cross-site",
}


def build_ydl_options(
    task: DownloadTask,
    download_dir: str,
    progress_hook: Callable[[dict[str, Any]], None],
    postprocessor_hook: Callable[[dict[str, Any]], None],
    custom_headers: dict[str, str] | None = None,
) -> dict:
    """Builds yt-dlp configuration options based on task quality and target format."""
    clean_base = None
    if task.title and not is_generic_title(task.title):
        clean_base = sanitize_filename(task.title)

    if clean_base:
        out_template = os.path.join(download_dir, f"{clean_base}.%(ext)s")
    else:
        out_template = os.path.join(download_dir, "%(title).150s.%(ext)s")

    ydl_opts: dict[str, Any] = {
        "outtmpl": out_template,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "quiet": True,
        "no_warnings": True,
        "windowsfilenames": True,
        "restrictfilenames": False,
        "nocheckcertificate": True,
        "overwrites": True,
    }

    # Format / Quality configuration
    q = task.quality.lower()
    target_fmt = task.format.lower()

    if q == "audio":
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    elif q == "1080p":
        ydl_opts["format"] = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
        if target_fmt in ["mp4", "mkv"]:
            ydl_opts["merge_output_format"] = target_fmt
    elif q == "720p":
        ydl_opts["format"] = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
        if target_fmt in ["mp4", "mkv"]:
            ydl_opts["merge_output_format"] = target_fmt
    elif q == "480p":
        ydl_opts["format"] = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
        if target_fmt in ["mp4", "mkv"]:
            ydl_opts["merge_output_format"] = target_fmt
    else:  # "best"
        ydl_opts["format"] = "bestvideo*+bestaudio/best"
        if target_fmt in ["mp4", "mkv"]:
            ydl_opts["merge_output_format"] = target_fmt

    # Prepare HTTP headers with modern browser defaults and CORS player semantics
    headers = dict(DEFAULT_HTTP_HEADERS)
    if custom_headers:
        for k, v in custom_headers.items():
            if not v:
                continue
            k_lower = k.lower()
            if k_lower == "user-agent":
                headers["User-Agent"] = v
            elif k_lower == "referer":
                headers["Referer"] = v
            elif k_lower == "origin":
                headers["Origin"] = v
            elif k_lower == "cookie":
                headers["Cookie"] = v
            else:
                headers[k] = v

    # Auto-derive Origin from Referer if missing
    referer_val = headers.get("Referer")
    if referer_val and not headers.get("Origin"):
        try:
            parsed_ref = urllib.parse.urlparse(referer_val)
            if parsed_ref.scheme and parsed_ref.netloc:
                headers["Origin"] = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
        except (ValueError, AttributeError) as e:
            logger.debug(f"Failed to derive Origin from Referer {referer_val}: {e}")

    ydl_opts["http_headers"] = headers
    ydl_opts["concurrent_fragment_downloads"] = 1

    return ydl_opts


class DownloadCancelledError(Exception):
    """Raised when a download task is cancelled by user."""


def execute_download(
    task: DownloadTask,
    download_dir: str | None = None,
    doodstream_resolver: Callable[..., tuple | None] | None = None,
):
    """
    Executes a single DownloadTask using yt-dlp, handling progress tracking,
    embed resolution, pre-extraction, and cleanup on failure or cancellation.

    Cancellation & Exception Unwinding Rationale:
    When aborting downloads via exceptions in callbacks/hooks (e.g. yt-dlp progress hooks),
    third-party engines often skip internal cleanup routines like _finish_frag_download.
    Unhandled exception tracebacks retain frame locals and closures in cyclic memory,
    keeping underlying file handles (io.BufferedWriter / _io.FileIO) open and locking files
    on Windows ([WinError 32]).
    To release handles safely on cancellation/failure, execution engines must:
      1. Identify and call .close() on task-scoped open stream objects (via cleanup_task_files / release_file_handles).
      2. Break exception references explicitly (`del e`).
      3. Invoke `gc.collect()` to finalize underlying OS file descriptors before attempting file deletion or returning.
    """
    if not download_dir:
        settings = load_settings()
        download_dir = settings.get("download_dir")
    os.makedirs(download_dir, exist_ok=True)

    # Verify cancellation state before transitioning to downloading to prevent
    # thread startup race conditions from overwriting user cancellation.
    if task.cancel_requested or task.status == "cancelled":
        logger.info(f"Task {task.id} was cancelled before download began.")
        task.status = "cancelled"
        task.completed_at = time.time()
        cleanup_task_files(task, download_dir)
        return

    task.status = "downloading"
    task.started_at = time.time()
    logger.info(f"Starting download for task {task.id}: {task.url}")

    download_url = task.url
    download_headers = dict(task.headers)

    # Automatic Doodstream resolution if an embed/page link was passed
    if is_doodstream_url(download_url) and "/pass_md5/" not in download_url and "?" not in download_url:
        resolver = doodstream_resolver or resolve_doodstream
        resolved = resolver(download_url, download_headers)
        if resolved:
            download_url, extra_headers = resolved
            download_headers.update(extra_headers)

    def progress_hook(d):
        if task.cancel_requested:
            raise DownloadCancelledError("Download cancelled by user.")

        status = d.get("status")
        fn = d.get("filename")
        tmpfn = d.get("tmpfilename")
        if fn:
            task.tracked_files.add(os.path.abspath(fn))
            if not task.filename:
                task.filepath = os.path.abspath(fn)
                task.filename = os.path.basename(fn)
        if tmpfn:
            task.tracked_files.add(os.path.abspath(tmpfn))

        if status == "downloading":
            task.status = "downloading"
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            speed = d.get("speed") or 0
            eta = d.get("eta")

            # Handle HLS fragments progress if byte count isn't available
            frag_index = d.get("fragment_index")
            frag_count = d.get("fragment_count")

            if total > 0:
                task.progress = round((downloaded / total) * 100, 1)
                task.total_bytes = total
            elif frag_count and frag_count > 0:
                task.progress = round((frag_index / frag_count) * 100, 1)
            elif "_percent_str" in d:
                try:
                    clean_str = re.sub(r'[^\d.]', '', d["_percent_str"])
                    task.progress = float(clean_str)
                except (ValueError, TypeError) as e:
                    logger.debug(f"Failed to parse percent string {d.get('_percent_str')}: {e}")

            task.downloaded_bytes = downloaded
            task.speed_raw = speed
            task.speed = f"{format_bytes(speed)}/s" if speed else "Calculating..."
            task.eta = format_eta(eta)

        elif status == "finished":
            task.status = "processing"
            task.progress = 100.0
            task.speed = "Finalizing..."
            task.eta = "00:00"
            if fn:
                task.filepath = os.path.abspath(fn)
                task.filename = os.path.basename(fn)

    def postprocessor_hook(d):
        if task.cancel_requested:
            raise DownloadCancelledError("Download cancelled by user.")
        fn = d.get("filepath")
        if fn:
            task.tracked_files.add(os.path.abspath(fn))
            if d.get("status") == "finished":
                task.filepath = os.path.abspath(fn)
                task.filename = os.path.basename(fn)

    ydl_opts = build_ydl_options(
        task=task,
        download_dir=download_dir,
        progress_hook=progress_hook,
        postprocessor_hook=postprocessor_hook,
        custom_headers=download_headers if download_headers else None,
    )

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # First extract info (without re-downloading if we can fetch title/thumbnail)
            try:
                info = ydl.extract_info(download_url, download=False)
                if info:
                    extracted = info.get("title")
                    if extracted and not is_generic_title(extracted) and is_generic_title(task.title):
                        task.title = extracted
                    task.thumbnail = info.get("thumbnail") or task.thumbnail

                    # Check planned filename and disambiguate if colliding on disk
                    try:
                        planned_fn = ydl.prepare_filename(info)
                        if planned_fn:
                            planned_stem = os.path.splitext(os.path.basename(planned_fn))[0]
                            unique_stem = get_unique_base(download_dir, planned_stem)
                            if unique_stem != planned_stem:
                                task.title = unique_stem
                                if "outtmpl" in ydl.params and isinstance(ydl.params["outtmpl"], dict):
                                    ydl.params["outtmpl"]["default"] = os.path.join(
                                        download_dir, f"{sanitize_filename(unique_stem)}.%(ext)s"
                                    )
                                planned_fn = ydl.prepare_filename(info)

                            task.tracked_files.add(os.path.abspath(planned_fn))
                            if not task.filepath:
                                task.filepath = os.path.abspath(planned_fn)
                                task.filename = os.path.basename(planned_fn)
                    except (KeyError, ValueError, TypeError, AttributeError, OSError) as plan_err:
                        logger.debug(f"Planned filename estimation non-fatal warning: {plan_err}")
            except Exception as extract_err:  # noqa: BLE001 - non-fatal pre-extraction failure should not abort download
                logger.debug(f"Pre-extraction info non-fatal warning: {extract_err}")

            if task.cancel_requested:
                raise DownloadCancelledError("Download cancelled by user.")

            # Perform actual download
            info = ydl.extract_info(download_url, download=True)
            if info:
                extracted = info.get("title")
                if extracted and not is_generic_title(extracted) and is_generic_title(task.title):
                    task.title = extracted
                task.thumbnail = info.get("thumbnail") or task.thumbnail

                # Track files from info dict
                if "_filename" in info:
                    task.tracked_files.add(os.path.abspath(info["_filename"]))
                if "requested_downloads" in info:
                    for req in info["requested_downloads"]:
                        if "_filename" in req:
                            task.tracked_files.add(os.path.abspath(req["_filename"]))

                # Determine final output file if not already detected
                if not task.filepath and "_filename" in info:
                    task.filepath = os.path.abspath(info["_filename"])
                    task.filename = os.path.basename(info["_filename"])
                elif not task.filepath and "requested_downloads" in info:
                    req = info["requested_downloads"][0]
                    if "_filename" in req:
                        task.filepath = os.path.abspath(req["_filename"])
                        task.filename = os.path.basename(req["_filename"])

        if is_generic_title(task.title):
            task.title = task.filename or f"Video {time.strftime('%Y-%m-%d %H:%M')}"

        task.status = "completed"
        task.progress = 100.0
        task.completed_at = time.time()
        task.speed = "0 B/s"
        task.eta = "00:00"
        logger.info(f"Task {task.id} completed successfully: {task.filename}")

    except Exception as e:  # noqa: BLE001 - top-level thread boundary catches all errors to prevent hung tasks
        is_cancelled = task.cancel_requested or isinstance(e, DownloadCancelledError) or "cancelled by user" in str(e).lower()
        if is_cancelled:
            task.status = "cancelled"
            logger.info(f"Task {task.id} was cancelled. Cleaning up temporary files...")
            cleanup_task_files(task, download_dir)
        else:
            task.status = "failed"
            task.error_message = str(e)
            logger.error(f"Task {task.id} failed: {e}")
        task.completed_at = time.time()
        del e
        gc.collect()
