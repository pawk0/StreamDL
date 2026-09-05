import gc
import io
import logging
import os
import re
import time
from collections.abc import Iterable

from server.config import load_settings
from server.task import DownloadTask
from server.utils import is_generic_title, sanitize_filename

logger = logging.getLogger("video_dl.cleanup")


def _is_task_file(candidate_abs: str, targets: set) -> bool:
    """Checks whether candidate_abs strictly matches any tracked target path or its partial/format variants."""
    if not targets:
        return False

    cand_lower = os.path.abspath(candidate_abs).lower()
    cand_dir = os.path.dirname(cand_lower)
    cand_fn = os.path.basename(cand_lower)

    for t in targets:
        t_lower = os.path.abspath(t).lower()
        t_dir = os.path.dirname(t_lower)
        if cand_dir != t_dir:
            continue
        t_fn = os.path.basename(t_lower)

        # 1. Exact match
        if cand_fn == t_fn:
            return True

        # 2. Suffix / fragment match: target.mp4.part, target.mp4.ytdl, target.mp4.part-Frag*.part
        if cand_fn.startswith(t_fn + ".") or cand_fn.startswith(t_fn + "-"):
            return True

        # 3. Base stream variants (e.g. format streams target.f137.mp4.part or target.temp.mp4)
        base_fn, _ = os.path.splitext(t_fn)
        if base_fn and cand_fn.startswith(base_fn + "."):
            if cand_fn.startswith(base_fn + ".temp.") or cand_fn == (base_fn + ".temp"):
                return True
            if re.search(r"^" + re.escape(base_fn) + r"\.f(\d+|ba|bv|hls|dash|audio|video|[0-9]+p)[a-zA-Z0-9_-]*\.(mp4|m4a|webm|mkv|mp3|ogg|wav|aac|flv|ts)(\.|$)", cand_fn):
                return True

    return False


def release_file_handles(download_dir: str, task_filepaths: Iterable[str] | None = None) -> int:
    """
    Scans for open Python file streams (io.IOBase) matching tracked task filepaths,
    closes them, and forces cyclic garbage collection.

    Windows File Lock / Exception Unwinding Rationale:
    When aborting downloads via exceptions in callbacks/hooks (e.g. yt-dlp progress hooks),
    third-party engines often skip cleanup routines like _finish_frag_download.
    Unhandled exception tracebacks retain frame locals and closures in cyclic memory,
    keeping underlying file handles (io.BufferedWriter / _io.FileIO) open and locking files
    on Windows ([WinError 32]).
    By scanning gc.get_objects() and matching only files associated with the target task,
    we explicitly close orphaned streams and invoke gc.collect() to finalize OS descriptors
    without disturbing active write streams of concurrent downloads in the same directory.
    """
    closed_count = 0
    targets = set()
    if task_filepaths:
        for p in task_filepaths:
            if p:
                targets.add(os.path.abspath(p).lower())

    if not targets:
        gc.collect()
        return 0

    for obj in gc.get_objects():
        try:
            if isinstance(obj, io.IOBase) and not obj.closed:
                name = getattr(obj, "name", None)
                if name and isinstance(name, str):
                    abs_name = os.path.abspath(name).lower()
                    if _is_task_file(abs_name, targets):
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
    Attempts to remove a file, retrying with bounded backoff if temporarily locked
    by the Windows filesystem.

    NTFS Latency Rationale:
    On Windows NTFS, file handle release by the OS can experience brief latency after
    Python stream close and garbage collection. Bounded retries (default 5 attempts with
    100ms backoff) tolerate this delay before logging warnings or failing.
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


def cleanup_task_files(task: DownloadTask, download_dir: str | None = None) -> list[str]:
    """
    Identifies and removes all incomplete, temporary, and fragment files for a cancelled task.

    Comprehensive Cleanup Matrix:
    Cancellation sweeps purge the following task-associated artifacts:
      - Main output file (if incomplete or cancelled mid-stream)
      - Partial files (*.part)
      - yt-dlp resume state files (*.ytdl)
      - Stream fragments (*-Frag*.part)
      - Intermediate format streams matching strict .f<fmt>. boundaries
        (e.g., .f(\\d+|ba|bv|...).part or format-specific extensions)
      - Temporary outputs modified during the task's lifetime.
    All sweeps are strictly scoped to the task's stems or tracked paths to prevent
    colliding with legitimate user files or concurrent tasks.
    """
    if not download_dir:
        settings = load_settings()
        download_dir = settings.get("download_dir")

    if not download_dir or not os.path.exists(download_dir):
        return []

    target_filename = task.filename or (os.path.basename(task.filepath) if task.filepath else None)
    clean_title = sanitize_filename(task.title) if (task.title and not is_generic_title(task.title)) else None
    task_started_at = task.started_at or task.created_at

    # Build comprehensive target paths for this task
    all_tracked = set()
    for f in task.tracked_files:
        if f:
            all_tracked.add(os.path.abspath(f))
    if task.filepath:
        all_tracked.add(os.path.abspath(task.filepath))
    elif target_filename:
        all_tracked.add(os.path.abspath(os.path.join(download_dir, target_filename)))
    elif clean_title:
        all_tracked.add(os.path.abspath(os.path.join(download_dir, clean_title)))

    # Ensure open Python file streams belonging to THIS task are closed first
    release_file_handles(download_dir, all_tracked)

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
        fp_abs = os.path.abspath(fp)
        fn_lower = fn.lower()

        try:
            mtime = os.path.getmtime(fp)
        except OSError:
            mtime = 0

        # Check if the file strictly belongs to this task
        if _is_task_file(fp_abs, all_tracked):
            # If it is the exact finished output file, only delete if modified during this task run
            # to avoid deleting pre-existing completed files.
            is_exact_output = False
            for t in all_tracked:
                if fp_abs.lower() == os.path.abspath(t).lower():
                    is_exact_output = True
                    break

            if is_exact_output:
                if mtime >= (task_started_at - 2):
                    should_remove = True
            else:
                # Suffixes (.part, .ytdl, -Frag*.part, .temp, .f<fmt>.) belonging to this task
                should_remove = True

        # Fallback: if filename was not known and title was used
        elif not target_filename and clean_title:
            ct_lower = clean_title.lower()
            if fn_lower.startswith(ct_lower + "."):
                is_temp_or_part = any(ext in fn_lower for ext in [".part", ".ytdl", ".temp"])
                is_format_stream = bool(re.search(
                    r"^" + re.escape(ct_lower) + r"\.f(\d+|ba|bv|hls|dash|audio|video|[0-9]+p)[a-zA-Z0-9_-]*\.(mp4|m4a|webm|mkv|mp3|ogg|wav|aac|flv|ts)(\.|$)",
                    fn_lower
                ))
                is_title_temp_media = bool(re.search(
                    r"^" + re.escape(ct_lower) + r"\.(mp4|m4a|webm|mkv|mp3|ogg|wav|aac|flv|ts)(\.(part|ytdl|temp))(-frag\d+\.part)?$",
                    fn_lower
                ))
                if is_format_stream or is_title_temp_media or fn_lower.startswith(ct_lower + ".temp.") or fn_lower == (ct_lower + ".temp"):
                    should_remove = True
                elif is_temp_or_part and mtime >= (task_started_at - 2):
                    if re.match(r"^" + re.escape(ct_lower) + r"\.[a-zA-Z0-9]{2,5}\.(part|ytdl)", fn_lower):
                        should_remove = True

        if should_remove:
            if remove_file_with_retry(fp):
                deleted.append(fp)

    gc.collect()
    if deleted:
        logger.info(f"Task {task.id} cleanup deleted {len(deleted)} file(s): {[os.path.basename(f) for f in deleted]}")
    return deleted

