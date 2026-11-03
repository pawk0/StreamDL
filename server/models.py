"""Typed HTTP contracts. Captured URLs and headers deliberately remain plain strings."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Quality = Literal["best", "1080p", "720p", "480p", "audio"]
MediaFormat = Literal["mp4", "mkv", "mp3"]


class DownloadRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "url": "https://media.example.com/master.m3u8",
                    "title": "Example video",
                    "quality": "720p",
                    "format": "mp4",
                    "headers": {"Referer": "https://player.example.com/"},
                }
            ]
        }
    )
    url: str
    title: str | None = None
    quality: Quality = "best"
    format: MediaFormat = "mp4"
    headers: dict[str, str] | None = None
    referer: str | None = None
    provider: str | None = None

    @field_validator("url")
    @classmethod
    def nonblank_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("URL must not be blank")
        return value.strip()


class Provider(BaseModel):
    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Provider name must not be blank")
        return value.strip()

    id: str = ""
    name: str
    patterns: str | list[str] = Field(default_factory=list)
    max_concurrent: int | None = Field(default=None, ge=1, le=10)


class SettingsPatch(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"max_concurrent": 4, "tls_mode": "strict"}]}
    )

    @field_validator("download_dir")
    @classmethod
    def nonblank_directory(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Download directory must not be blank")
        return value.strip()

    download_dir: str = Field(default="", min_length=1)
    max_concurrent: int = Field(default=3, ge=1, le=10)
    max_concurrent_per_provider: int = Field(default=1, ge=1, le=10)
    default_quality: Quality = "best"
    default_format: MediaFormat = "mp4"
    port: int = Field(default=7921, ge=1, le=65535)
    providers: list[Provider] = Field(default_factory=list)
    allowed_origins: list[str] = Field(default_factory=list)
    tls_mode: Literal["auto", "strict", "permissive"] = "auto"
    tls_verify: bool = True
    check_certificate: bool = True


class FolderRequest(BaseModel):
    folder: str | None = None


class TaskResponse(BaseModel):
    id: str
    url: str
    title: str
    quality: str
    format: str
    provider: str
    provider_id: str
    provider_limit: int
    status: str
    progress: float
    speed: str
    speed_raw: float
    downloaded_bytes: int
    downloaded_str: str
    # yt-dlp's total_bytes_estimate can contain fractional bytes.
    total_bytes: int | float
    total_str: str
    eta: str
    error_message: str | None
    filename: str | None
    filepath: str | None
    thumbnail: str | None
    created_at: float
    started_at: float | None
    completed_at: float | None


class ProviderResponse(BaseModel):
    id: str
    name: str
    patterns: list[str]
    max_concurrent: int | None = None


class SettingsResponse(BaseModel):
    download_dir: str
    max_concurrent: int
    max_concurrent_per_provider: int
    default_quality: str
    default_format: str
    port: int
    providers: list[ProviderResponse]
    allowed_origins: list[str]
    tls_mode: str


class ActionResponse(BaseModel):
    success: bool
    message: str | None = None
    task: TaskResponse | None = None
    settings: SettingsResponse | None = None
    path: str | None = None
    file: str | None = None


class QueueResponse(BaseModel):
    tasks: list[TaskResponse]
    active_count: int
    queued_count: int
    max_concurrent: int
    max_concurrent_per_provider: int
    providers: list[ProviderResponse]
    download_dir: str | None


class StatusResponse(BaseModel):
    status: str
    version: str
    active_count: int
    queued_count: int
    completed_count: int
    total_tasks: int
    max_concurrent: int
    max_concurrent_per_provider: int
    download_dir: str | None


class DomainError(BaseModel):
    success: bool = False
    error: str
