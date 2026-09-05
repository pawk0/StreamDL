import json
import os
import re
import fnmatch
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple, List, Dict

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

DEFAULT_PROVIDERS: List[Dict] = [
    {
        "id": "doodstream",
        "name": "Doodstream",
        "patterns": ["*dood*", "*cloudatacdn.com*"],
        "max_concurrent": 1
    }
]

DEFAULT_SETTINGS = {
    "download_dir": DEFAULT_DOWNLOAD_DIR,
    "max_concurrent": 3,
    "max_concurrent_per_provider": 1,
    "providers": DEFAULT_PROVIDERS,
    "default_quality": "best",
    "default_format": "mp4",
    "port": 7921,
}

def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    # Deep copy default providers
    settings["providers"] = [dict(p) for p in DEFAULT_PROVIDERS]
    
    settings_file = get_settings_file()
    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                settings.update(data)
        except Exception as e:
            print(f"Error loading settings: {e}")

    # Environment port override
    if "VIDEO_DL_PORT" in os.environ:
        try:
            settings["port"] = int(os.environ["VIDEO_DL_PORT"])
        except (ValueError, TypeError):
            pass

    # Ensure providers list exists and is well-formed
    if not settings.get("providers") or not isinstance(settings.get("providers"), list):
        settings["providers"] = [dict(p) for p in DEFAULT_PROVIDERS]
    if "max_concurrent_per_provider" not in settings:
        settings["max_concurrent_per_provider"] = 1

    # Ensure download directory exists
    try:
        os.makedirs(settings["download_dir"], exist_ok=True)
    except Exception:
        pass
    return settings

def save_settings(new_settings: dict) -> dict:
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
                except Exception:
                    pass
            settings[k] = val

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
        if cleaned_providers:
            settings["providers"] = cleaned_providers

    settings_file = get_settings_file()
    try:
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Error saving settings: {e}")

    return settings


def match_provider(url: str, referer: Optional[str] = None, settings: Optional[dict] = None) -> Tuple[str, str, int]:
    """
    Matches a URL and referer against configured providers.
    Returns (provider_id, provider_name, provider_concurrency_limit).
    """
    if settings is None:
        settings = load_settings()

    default_limit = settings.get("max_concurrent_per_provider", 1)
    providers = settings.get("providers") or DEFAULT_PROVIDERS

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
        except Exception:
            pass

    return domain.lower(), domain, default_limit

