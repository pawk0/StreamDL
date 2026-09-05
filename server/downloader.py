import os
import re
import time
import uuid
import logging
import threading
from typing import Dict, List, Optional
import yt_dlp

from server.config import load_settings

logger = logging.getLogger("video_dl.downloader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def format_bytes(b: Optional[float]) -> str:
    if not b or b <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PB"


def format_eta(seconds: Optional[int]) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class DownloadTask:
    def __init__(
        self,
        task_id: str,
        url: str,
        title: Optional[str] = None,
        quality: str = "best",
        fmt: str = "mp4",
        headers: Optional[Dict[str, str]] = None,
    ):
        self.id = task_id
        self.url = url
        self.title = title or "Fetching info..."
        self.quality = quality
        self.format = fmt
        self.headers = headers or {}
        
        self.status = "queued"  # queued, downloading, processing, completed, failed, cancelled
        self.progress = 0.0  # 0.0 to 100.0
        self.speed = "0 B/s"
        self.speed_raw = 0
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.eta = "--:--"
        self.error_message: Optional[str] = None
        self.filepath: Optional[str] = None
        self.filename: Optional[str] = None
        self.thumbnail: Optional[str] = None

        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        
        self.cancel_requested = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "quality": self.quality,
            "format": self.format,
            "status": self.status,
            "progress": self.progress,
            "speed": self.speed,
            "speed_raw": self.speed_raw,
            "downloaded_bytes": self.downloaded_bytes,
            "downloaded_str": format_bytes(self.downloaded_bytes),
            "total_bytes": self.total_bytes,
            "total_str": format_bytes(self.total_bytes) if self.total_bytes > 0 else "Unknown",
            "eta": self.eta,
            "error_message": self.error_message,
            "filename": self.filename,
            "filepath": self.filepath,
            "thumbnail": self.thumbnail,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class DownloadManager:
    _instance = None

    def __init__(self):
        self._lock = threading.Lock()
        self.tasks: Dict[str, DownloadTask] = {}
        self.task_order: List[str] = []
        self._active_threads: Dict[str, threading.Thread] = {}
        self._stop_dispatcher = False
        
        # Start background queue dispatcher
        self._dispatcher_thread = threading.Thread(target=self._dispatcher_loop, daemon=True)
        self._dispatcher_thread.start()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def add_task(
        self,
        url: str,
        title: Optional[str] = None,
        quality: str = "best",
        fmt: str = "mp4",
        headers: Optional[Dict[str, str]] = None,
    ) -> DownloadTask:
        task_id = str(uuid.uuid4())[:8]
        task = DownloadTask(
            task_id=task_id,
            url=url,
            title=title,
            quality=quality,
            fmt=fmt,
            headers=headers,
        )
        with self._lock:
            self.tasks[task_id] = task
            self.task_order.append(task_id)
        logger.info(f"Task {task_id} added to queue for {url}")
        return task

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            if task.status in ["completed", "failed", "cancelled"]:
                return False
            
            task.cancel_requested = True
            if task.status == "queued":
                task.status = "cancelled"
                task.completed_at = time.time()
                logger.info(f"Queued task {task_id} cancelled.")
                return True
            
            # If currently downloading, the hook will raise exception and terminate
            task.status = "cancelled"
            logger.info(f"Cancellation requested for active task {task_id}.")
            return True

    def clear_finished(self):
        with self._lock:
            to_remove = [
                tid for tid, t in self.tasks.items()
                if t.status in ["completed", "failed", "cancelled"]
            ]
            for tid in to_remove:
                del self.tasks[tid]
                if tid in self.task_order:
                    self.task_order.remove(tid)
        logger.info(f"Cleared {len(to_remove)} finished tasks.")

    def get_all_tasks(self) -> List[dict]:
        with self._lock:
            return [self.tasks[tid].to_dict() for tid in self.task_order if tid in self.tasks]

    def get_task(self, task_id: str) -> Optional[dict]:
        with self._lock:
            task = self.tasks.get(task_id)
            return task.to_dict() if task else None

    def _dispatcher_loop(self):
        while not self._stop_dispatcher:
            time.sleep(0.5)
            settings = load_settings()
            max_concurrent = settings.get("max_concurrent", 3)

            with self._lock:
                # Clean up finished threads
                finished_tids = [tid for tid, th in self._active_threads.items() if not th.is_alive()]
                for tid in finished_tids:
                    del self._active_threads[tid]

                active_count = len(self._active_threads)
                slots_available = max_concurrent - active_count

                if slots_available > 0:
                    for tid in self.task_order:
                        task = self.tasks.get(tid)
                        if task and task.status == "queued" and not task.cancel_requested:
                            # Start task in background thread
                            th = threading.Thread(
                                target=self._execute_download,
                                args=(task,),
                                daemon=True
                            )
                            self._active_threads[tid] = th
                            th.start()
                            slots_available -= 1
                            if slots_available <= 0:
                                break

    def _execute_download(self, task: DownloadTask):
        settings = load_settings()
        download_dir = settings.get("download_dir")
        os.makedirs(download_dir, exist_ok=True)

        task.status = "downloading"
        task.started_at = time.time()
        logger.info(f"Starting download for task {task.id}: {task.url}")

        def progress_hook(d):
            if task.cancel_requested:
                raise Exception("Download cancelled by user.")

            status = d.get("status")
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
                    except Exception:
                        pass

                task.downloaded_bytes = downloaded
                task.speed_raw = speed
                task.speed = f"{format_bytes(speed)}/s" if speed else "Calculating..."
                task.eta = format_eta(eta)

                # Capture filename if available
                fn = d.get("filename")
                if fn and not task.filename:
                    task.filepath = os.path.abspath(fn)
                    task.filename = os.path.basename(fn)

            elif status == "finished":
                task.status = "processing"
                task.progress = 100.0
                task.speed = "Finalizing..."
                task.eta = "00:00"
                fn = d.get("filename")
                if fn:
                    task.filepath = os.path.abspath(fn)
                    task.filename = os.path.basename(fn)

        def postprocessor_hook(d):
            if task.cancel_requested:
                raise Exception("Download cancelled by user.")
            if d.get("status") == "finished":
                fn = d.get("filepath")
                if fn:
                    task.filepath = os.path.abspath(fn)
                    task.filename = os.path.basename(fn)

        ydl_opts = {
            "outtmpl": os.path.join(download_dir, "%(title).120B [%(id)s].%(ext)s"),
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

        # Pass custom HTTP headers (e.g. Referer, User-Agent) if provided
        if task.headers:
            ydl_opts["http_headers"] = task.headers

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # First extract info (without re-downloading if we can fetch title/thumbnail)
                try:
                    info = ydl.extract_info(task.url, download=False)
                    if info:
                        task.title = info.get("title") or task.title
                        task.thumbnail = info.get("thumbnail")
                except Exception as extract_err:
                    logger.debug(f"Pre-extraction info non-fatal warning: {extract_err}")

                if task.cancel_requested:
                    raise Exception("Download cancelled by user.")

                # Perform actual download
                info = ydl.extract_info(task.url, download=True)
                if info:
                    task.title = info.get("title") or task.title
                    task.thumbnail = info.get("thumbnail") or task.thumbnail
                    
                    # Determine final output file if not already detected
                    if not task.filepath and "_filename" in info:
                        task.filepath = os.path.abspath(info["_filename"])
                        task.filename = os.path.basename(info["_filename"])
                    elif not task.filepath and "requested_downloads" in info:
                        req = info["requested_downloads"][0]
                        if "_filename" in req:
                            task.filepath = os.path.abspath(req["_filename"])
                            task.filename = os.path.basename(req["_filename"])

            task.status = "completed"
            task.progress = 100.0
            task.completed_at = time.time()
            task.speed = "0 B/s"
            task.eta = "00:00"
            logger.info(f"Task {task.id} completed successfully: {task.filename}")

        except Exception as e:
            if task.cancel_requested or "cancelled by user" in str(e).lower():
                task.status = "cancelled"
                logger.info(f"Task {task.id} was cancelled.")
            else:
                task.status = "failed"
                task.error_message = str(e)
                logger.error(f"Task {task.id} failed: {e}")
            task.completed_at = time.time()
