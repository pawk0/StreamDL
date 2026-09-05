import time
from typing import Dict, Optional, Set

from server.config import match_provider
from server.utils import format_bytes


class DownloadTask:
    """Encapsulates the lifecycle, metadata, and progress state of a single download."""

    def __init__(
        self,
        task_id: str,
        url: str,
        title: Optional[str] = None,
        quality: str = "best",
        fmt: str = "mp4",
        headers: Optional[Dict[str, str]] = None,
        provider_id: Optional[str] = None,
        provider_name: Optional[str] = None,
        provider_limit: Optional[int] = None,
    ):
        self.id = task_id
        self.url = url
        self.title = title or "Fetching info..."
        self.quality = quality
        self.format = fmt
        self.headers = headers or {}

        # Resolve provider
        referer = self.headers.get("Referer") or self.headers.get("referer")
        pid, pname, plimit = match_provider(url, referer)
        self.provider_id = provider_id or pid
        self.provider_name = provider_name or pname
        self.provider_limit = provider_limit or plimit

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
        self.tracked_files: Set[str] = set()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "quality": self.quality,
            "format": self.format,
            "provider": self.provider_name,
            "provider_id": self.provider_id,
            "provider_limit": self.provider_limit,
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
