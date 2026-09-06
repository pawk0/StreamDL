import logging
import threading
import time
import uuid

from server.cleanup import cleanup_task_files
from server.config import load_settings, match_provider
from server.engine import execute_download
from server.task import DownloadTask
from server.utils import (
    get_unique_base,
    is_generic_title,
    normalize_url,
    sanitize_filename,
)

logger = logging.getLogger("video_dl.downloader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class DuplicateTaskError(ValueError):
    """Raised when an identical task (same sanitized title and URL) is already queued or downloading."""



class DownloadManager:
    """
    Manages the queue, concurrency limits, and thread dispatching for downloads.
    Operates as a thread-safe singleton.
    """
    _instance = None

    def __init__(self):
        self._lock = threading.Lock()
        self.tasks: dict[str, DownloadTask] = {}
        self.task_order: list[str] = []
        self._active_threads: dict[str, threading.Thread] = {}
        self._reserved_names: dict[str, str] = {}
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
        title: str | None = None,
        quality: str = "best",
        fmt: str = "mp4",
        headers: dict[str, str] | None = None,
        provider_id: str | None = None,
        provider_name: str | None = None,
        provider_limit: int | None = None,
    ) -> DownloadTask:
        norm_url = normalize_url(url)
        clean_title = sanitize_filename(title) if title else None
        has_title = bool(clean_title and not is_generic_title(clean_title))
        clean_title_lower = clean_title.lower() if has_title else None

        task_id = str(uuid.uuid4())[:8]

        with self._lock:
            # Prune reservations for tasks that failed or were cancelled
            dead_ids = [
                tid for tid, t in self.tasks.items()
                if t.status in ["failed", "cancelled"] and tid in self._reserved_names
            ]
            for tid in dead_ids:
                del self._reserved_names[tid]

            # Check for duplicate tasks in active states
            for existing in self.tasks.values():
                if existing.status in ["queued", "downloading", "processing"]:
                    ex_clean = sanitize_filename(existing.title) if existing.title else None
                    ex_has_title = bool(ex_clean and not is_generic_title(ex_clean))
                    ex_sanitized = ex_clean.lower() if ex_has_title else None
                    ex_url = normalize_url(existing.url)

                    # Same sanitized name + same url -> reject
                    if clean_title_lower and ex_sanitized and clean_title_lower == ex_sanitized:
                        if norm_url == ex_url:
                            raise DuplicateTaskError(
                                f"Task with name '{title}' and URL '{url}' is already queued or downloading"
                            )
                    elif not clean_title_lower and not ex_sanitized and norm_url == ex_url:
                        raise DuplicateTaskError(
                            f"Task for '{url}' is already queued or downloading"
                        )

            # Compute unique title and register reservation under lock
            final_title = title
            if has_title:
                settings = load_settings()
                download_dir = settings.get("download_dir")
                reserved_set = set(self._reserved_names.values())
                final_title = get_unique_base(download_dir, title, reserved_names=reserved_set)
                self._reserved_names[task_id] = sanitize_filename(final_title).lower()

            task = DownloadTask(
                task_id=task_id,
                url=url,
                title=final_title,
                quality=quality,
                fmt=fmt,
                headers=headers,
                provider_id=provider_id,
                provider_name=provider_name,
                provider_limit=provider_limit,
            )
            self.tasks[task_id] = task
            self.task_order.append(task_id)

        logger.info(f"Task {task_id} [{task.provider_name}] added to queue for {url}")
        return task

    def cancel_task(self, task_id: str) -> bool:
        th = None
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
                self._reserved_names.pop(task_id, None)
                logger.info(f"Queued task {task_id} cancelled.")
                cleanup_task_files(task)
                return True

            # If currently downloading, the hook will raise exception and terminate
            task.status = "cancelled"
            self._reserved_names.pop(task_id, None)
            logger.info(f"Cancellation requested for active task {task_id}.")
            th = self._active_threads.get(task_id)

        # Wait briefly outside the lock for the thread to exit and execute cleanup
        if th and th.is_alive():
            th.join(timeout=1.5)

        # Ensure cleanup runs even if thread had not started downloading yet or took longer
        cleanup_task_files(task)
        return True

    def clear_finished(self):
        with self._lock:
            to_remove = [
                tid for tid, t in self.tasks.items()
                if t.status in ["completed", "failed", "cancelled"]
            ]
            for tid in to_remove:
                t = self.tasks[tid]
                if t.status == "cancelled":
                    cleanup_task_files(t)
                del self.tasks[tid]
                self._reserved_names.pop(tid, None)
                if tid in self.task_order:
                    self.task_order.remove(tid)
        logger.info(f"Cleared {len(to_remove)} finished tasks.")

    def get_all_tasks(self) -> list[dict]:
        with self._lock:
            return [self.tasks[tid].to_dict() for tid in self.task_order if tid in self.tasks]

    def get_task(self, task_id: str) -> dict | None:
        with self._lock:
            task = self.tasks.get(task_id)
            return task.to_dict() if task else None

    def rematch_providers(self, settings: dict | None = None):
        """
        Re-evaluates and updates provider assignments (provider_id, provider_name,
        and provider_limit) for all active and queued tasks in-memory.

        Live Rematching Invariant:
        Whenever provider definitions, URL patterns, or concurrency limits are updated in
        settings, this method dynamically reconciles in-flight and pending tasks without
        dropping task state, interrupting downloads, or requiring server restarts.
        """
        if settings is None:
            settings = load_settings()
        with self._lock:
            for task in self.tasks.values():
                referer = task.headers.get("Referer") or task.headers.get("referer")
                pid, pname, plimit = match_provider(task.url, referer, settings)
                task.provider_id = pid
                task.provider_name = pname
                task.provider_limit = plimit
        logger.info("Rematched tasks against updated provider configuration.")

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
                if active_count >= max_concurrent:
                    continue

                # Calculate active count per provider
                provider_counts: dict[str, int] = {}
                for tid in self._active_threads:
                    t = self.tasks.get(tid)
                    if t:
                        provider_counts[t.provider_id] = provider_counts.get(t.provider_id, 0) + 1

                slots_available = max_concurrent - active_count
                if slots_available > 0:
                    for tid in self.task_order:
                        task = self.tasks.get(tid)
                        if task and task.status == "queued" and not task.cancel_requested:
                            p_active = provider_counts.get(task.provider_id, 0)
                            # Dynamically resolve latest limit for this provider from settings
                            provider_entry = next((p for p in (settings.get("providers") or []) if p.get("id") == task.provider_id), None)
                            if provider_entry:
                                p_limit = provider_entry.get("max_concurrent") or settings.get("max_concurrent_per_provider", 1)
                            else:
                                p_limit = settings.get("max_concurrent_per_provider", 1)
                            task.provider_limit = p_limit

                            # If this provider has hit its concurrency limit, skip this task for now
                            if p_active >= p_limit:
                                continue

                            # Start task in background thread
                            task.status = "downloading"
                            th = threading.Thread(
                                target=self._execute_download,
                                args=(task,),
                                daemon=True
                            )
                            self._active_threads[tid] = th
                            th.start()
                            provider_counts[task.provider_id] = p_active + 1
                            slots_available -= 1
                            if slots_available <= 0:
                                break

    def _execute_download(self, task: DownloadTask):
        """Executes download delegating directly to the engine."""
        try:
            execute_download(task)
        finally:
            if task.status in ["failed", "cancelled"]:
                with self._lock:
                    self._reserved_names.pop(task.id, None)
