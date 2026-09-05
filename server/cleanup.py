import gc
import io
import logging
import os
import re
import time
from typing import Iterable, List, Optional

from server.config import load_settings
from server.task import DownloadTask
from server.utils import is_generic_title, sanitize_filename

logger = logging.getLogger("video_dl.cleanup")


def release_file_handles(download_dir: str, task_filepaths: Optional[Iterable[str]] = None) -> int:
    """
    Scans for open Python file streams (io.IOBase) within download_dir or matching
    tracked task filepaths, closes them, and forces cyclic garbage collection.
    This prevents Windows from locking files with [WinError 32] after cancellation.
    """
    closed_count = 0
    target_dir = os.path.abspath(download_dir).lower()
    targets = set()
    if task_filepaths:
        for p in task_filepaths:
            if p:
                targets.add(os.path.abspath(p).lower())

    for obj in gc.get_objects():
        try:
            if isinstance(obj, io.IOBase) and not obj.closed:
                name = getattr(obj, "name", None)
                if name and isinstance(name, str):
                    abs_name = os.path.abspath(name).lower()
                    if abs_name.startswith(target_dir) or any(abs_name.startswith(t) for t in targets):
                        try:
                            obj.close()
                            closed_count += 1
                        except Exception:
                            pass
        except Exception:
            pass

    gc.collect()
    return closed_count


def remove_file_with_retry(filepath: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    """
    Attempts to remove a file, retrying briefly if temporarily locked by Windows filesystem.
    """
    for attempt in range(max_retries):
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Removed temporary file: {filepath}")
            return True
        except (OSError, PermissionError) as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
                release_file_handles(os.path.dirname(filepath), [filepath])
            else:
                logger.warning(f"Could not remove file {filepath}: {e}")
                return False
    return True


def cleanup_task_files(task: DownloadTask, download_dir: Optional[str] = None) -> List[str]:
    """
    Identifies and removes all incomplete, temporary, and fragment files for a cancelled task.
    Handles *.part, *.ytdl, *.part-Frag*.part, format-specific intermediate files, and incomplete output files.
    """
    if not download_dir:
        settings = load_settings()
        download_dir = settings.get("download_dir")

    if not download_dir or not os.path.exists(download_dir):
        return []

    # Ensure any open Python file streams are closed and garbage collected first
    all_tracked = set(task.tracked_files)
    if task.filepath:
        all_tracked.add(os.path.abspath(task.filepath))
    release_file_handles(download_dir, all_tracked)

    target_filename = task.filename or (os.path.basename(task.filepath) if task.filepath else None)
    clean_title = sanitize_filename(task.title) if (task.title and not is_generic_title(task.title)) else None
    task_started_at = task.started_at or task.created_at

    deleted = []
    try:
        entries = os.listdir(download_dir)
    except Exception as e:
        logger.error(f"Failed to list download directory {download_dir}: {e}")
        return []

    for fn in entries:
        fp = os.path.join(download_dir, fn)
        if not os.path.isfile(fp):
            continue

        should_remove = False
        fp_abs = os.path.abspath(fp).lower()

        # Check if explicitly tracked
        for tracked in all_tracked:
            t_lower = tracked.lower()
            if fp_abs == t_lower or fp_abs.startswith(t_lower + ".") or fp_abs.startswith(t_lower + "-"):
                should_remove = True
                break

        # If not already matched, match via filename / title patterns
        if not should_remove:
            try:
                mtime = os.path.getmtime(fp)
            except OSError:
                mtime = 0

            fn_lower = fn.lower()
            is_temp_or_part = any(ext in fn_lower for ext in [".part", ".ytdl", ".temp"])

            # 1. Exact match with target_filename (incomplete output file modified during task)
            if target_filename and fn_lower == target_filename.lower():
                if mtime >= (task_started_at - 2):
                    should_remove = True

            # 2. Starts with target_filename (e.g. video.mp4.part, video.mp4.ytdl, video.mp4.part-Frag29.part)
            elif target_filename and (fn_lower.startswith(target_filename.lower() + ".") or fn_lower.startswith(target_filename.lower() + "-")):
                should_remove = True

            # 3. Base matching (e.g. video.f137.mp4, video.f137.mp4.part, video.f140.m4a.part)
            elif target_filename:
                base, _ = os.path.splitext(target_filename)
                if base and fn_lower.startswith(base.lower() + "."):
                    if is_temp_or_part or re.search(r"\.f[a-zA-Z0-9_-]+\.", fn_lower) or mtime >= (task_started_at - 2):
                        should_remove = True

            # 4. Clean title matching if target_filename wasn't resolved yet
            if not should_remove and clean_title:
                ct_lower = clean_title.lower()
                if fn_lower.startswith(ct_lower + "."):
                    if is_temp_or_part or re.search(r"\.f[a-zA-Z0-9_-]+\.", fn_lower) or mtime >= (task_started_at - 2):
                        should_remove = True

        if should_remove:
            if remove_file_with_retry(fp):
                deleted.append(fp)

    gc.collect()
    if deleted:
        logger.info(f"Task {task.id} cleanup deleted {len(deleted)} file(s): {[os.path.basename(f) for f in deleted]}")
    return deleted
