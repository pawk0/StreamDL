import copy
import fnmatch
import json
import logging
import os
import re
import threading
import urllib.parse
from pathlib import Path

logger = logging.getLogger("video_dl.config")

_settings_lock = threading.RLock()
_cached_settings: dict | None = None
_cached_path: Path | None = None
_cached_mtime: float | None = None
_cached_port_env: str | None = None


def clear_settings_cache() -> None:
    """Clears in-memory settings cache, forcing the next load_settings() to read from disk."""
    global _cached_settings, _cached_path, _cached_mtime, _cached_port_env
    with _settings_lock:
        _cached_settings = None
        _cached_path = None
        _cached_mtime = None
        _cached_port_env = None


def get_settings_file() -> Path:
    env_override = os.environ.get("VIDEO_DL_SETTINGS_FILE")
    if env_override:
        return Path(env_override)
    return Path(__file__).parent.parent / "settings.json"


def __getattr__(name: str):
    if name == "SETTINGS_FILE":
        return get_settings_file()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Downloads" / "VideoDL")

DEFAULT_PROVIDERS: list[dict] = [
    {
        "id": "doodstream",
        "name": "Doodstream",
        "patterns": ["*dood*", "*cloudatacdn.com*"],
        "max_concurrent": 1
    },
    {
        "id": "lulustream",
        "name": "LuluStream",
        "patterns": ["*cdn-tnmr.org*", "*lulustream*", "*luluvdo*", "*luluvid*", "*lulu.st*"],
        "max_concurrent": 1
    }
]

DEFAULT_ALLOWED_ORIGIN_PATTERNS: list[str] = [
    r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    r"^chrome-extension://.*",
    r"^moz-extension://.*",
    r"^extension://.*",
]

DEFAULT_SETTINGS = {
    "download_dir": DEFAULT_DOWNLOAD_DIR,
    "max_concurrent": 3,
    "max_concurrent_per_provider": 1,
    "providers": DEFAULT_PROVIDERS,
    "default_quality": "best",
    "default_format": "mp4",
    "port": 7921,
    "allowed_origins": list(DEFAULT_ALLOWED_ORIGIN_PATTERNS),
}


def load_settings(force_reload: bool = False) -> dict:
    global _cached_settings, _cached_path, _cached_mtime, _cached_port_env
    with _settings_lock:
        settings_file = get_settings_file()
        current_port_env = os.environ.get("VIDEO_DL_PORT")

        file_mtime: float | None = None
        file_exists = settings_file.exists()
        if file_exists:
            try:
                file_mtime = settings_file.stat().st_mtime
            except OSError:
                file_mtime = None

        if (
            not force_reload
            and _cached_settings is not None
            and _cached_path == settings_file
            and _cached_mtime == file_mtime
            and _cached_port_env == current_port_env
        ):
            return copy.deepcopy(_cached_settings)

        settings = dict(DEFAULT_SETTINGS)
        # Deep copy default providers
        settings["providers"] = [dict(p) for p in DEFAULT_PROVIDERS]
        settings["allowed_origins"] = list(DEFAULT_ALLOWED_ORIGIN_PATTERNS)

        if file_exists:
            try:
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    settings.update(data)
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"Error loading settings: {e}")

        # Environment port override
        if current_port_env is not None:
            try:
                settings["port"] = int(current_port_env)
            except (ValueError, TypeError):
                pass

        # Ensure providers list exists and is well-formed (preserves explicitly configured empty list)
        if settings.get("providers") is None or not isinstance(settings.get("providers"), list):
            settings["providers"] = [dict(p) for p in DEFAULT_PROVIDERS]
        if "max_concurrent_per_provider" not in settings:
            settings["max_concurrent_per_provider"] = 1
        if not settings.get("allowed_origins") or not isinstance(settings.get("allowed_origins"), list):
            settings["allowed_origins"] = list(DEFAULT_ALLOWED_ORIGIN_PATTERNS)

        # Ensure download directory exists
        download_dir = settings.get("download_dir")
        if isinstance(download_dir, str):
            try:
                os.makedirs(download_dir, exist_ok=True)
            except OSError as e:
                logger.warning(f"Could not create download directory {download_dir}: {e}")

        _cached_settings = copy.deepcopy(settings)
        _cached_path = settings_file
        _cached_mtime = file_mtime
        _cached_port_env = current_port_env

        return copy.deepcopy(settings)


def save_settings(new_settings: dict) -> dict:
    global _cached_settings, _cached_path, _cached_mtime, _cached_port_env
    with _settings_lock:
        settings = load_settings()
        for k in ["download_dir", "max_concurrent", "max_concurrent_per_provider", "default_quality", "default_format", "port"]:
            if k in new_settings:
                val = new_settings[k]
                if k in ["max_concurrent", "max_concurrent_per_provider"]:
                    try:
                        val = max(1, min(10, int(val)))
                    except (ValueError, TypeError):
                        continue
                elif k == "download_dir":
                    val = str(val).strip()
                    if not val:
                        continue
                    try:
                        os.makedirs(val, exist_ok=True)
                    except OSError as e:
                        logger.warning(f"Could not create download directory {val}: {e}")
                settings[k] = val

        if "allowed_origins" in new_settings and isinstance(new_settings["allowed_origins"], list):
            cleaned_origins = [str(o).strip() for o in new_settings["allowed_origins"] if str(o).strip()]
            if cleaned_origins:
                settings["allowed_origins"] = cleaned_origins

        if "providers" in new_settings and isinstance(new_settings["providers"], list):
            cleaned_providers = []
            for p in new_settings["providers"]:
                if not isinstance(p, dict):
                    continue
                name = str(p.get("name", "")).strip()
                if not name:
                    continue
                pid = str(p.get("id", "")).strip().lower() or re.sub(r'[^a-zA-Z0-9_-]', '', name.lower())
                raw_patterns = p.get("patterns", [])
                if isinstance(raw_patterns, str):
                    patterns = [x.strip() for x in raw_patterns.split(",") if x.strip()]
                elif isinstance(raw_patterns, list):
                    patterns = [str(x).strip() for x in raw_patterns if str(x).strip()]
                else:
                    patterns = []

                max_c = p.get("max_concurrent")
                if max_c is not None:
                    try:
                        max_c = max(1, min(10, int(max_c)))
                    except (ValueError, TypeError):
                        max_c = settings.get("max_concurrent_per_provider", 1)
                else:
                    max_c = settings.get("max_concurrent_per_provider", 1)

                cleaned_providers.append({
                    "id": pid,
                    "name": name,
                    "patterns": patterns,
                    "max_concurrent": max_c
                })
            # Always assign cleaned_providers if "providers" is in new_settings, allowing clearance to []
            settings["providers"] = cleaned_providers

        settings_file = get_settings_file()
        temp_file = settings_file.parent / f".{settings_file.name}.{os.getpid()}_{threading.get_ident()}.tmp"
        try:
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
            os.replace(temp_file, settings_file)
            new_mtime = settings_file.stat().st_mtime
        except OSError as e:
            logger.error(f"Error saving settings: {e}")
            new_mtime = None
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

        _cached_settings = copy.deepcopy(settings)
        _cached_path = settings_file
        _cached_mtime = new_mtime
        _cached_port_env = os.environ.get("VIDEO_DL_PORT")

        return copy.deepcopy(settings)


def match_provider(url: str, referer: str | None = None, settings: dict | None = None) -> tuple[str, str, int]:
    """
    Matches a URL and referer against configured providers.
    Returns (provider_id, provider_name, provider_concurrency_limit).
    """
    if settings is None:
        settings = load_settings()

    default_limit = settings.get("max_concurrent_per_provider", 1)
    providers = settings.get("providers")
    if providers is None or not isinstance(providers, list):
        providers = DEFAULT_PROVIDERS

    candidates = []
    if url:
        candidates.append(url)
    if referer:
        candidates.append(referer)

    for p in providers:
        p_patterns = p.get("patterns", [])
        for pattern in p_patterns:
            pat = pattern.strip().lower()
            if not pat:
                continue
            if "*" not in pat:
                pat = f"*{pat}*"
            for c in candidates:
                c_lower = c.lower()
                if fnmatch.fnmatch(c_lower, pat):
                    limit = p.get("max_concurrent") or default_limit
                    return p.get("id", "provider"), p.get("name", "Provider"), limit

    # Fallback: extract root domain from URL or referer
    domain = "Direct"
    for c in candidates:
        try:
            parsed = urllib.parse.urlparse(c)
            netloc = parsed.netloc.split(":")[0].lower()
            if netloc:
                parts = netloc.split(".")
                if len(parts) >= 2:
                    domain = ".".join(parts[-2:])
                else:
                    domain = netloc
                break
        except (ValueError, AttributeError) as e:
            logger.debug(f"Failed to parse candidate URL {c}: {e}")

    return domain.lower(), domain, default_limit

