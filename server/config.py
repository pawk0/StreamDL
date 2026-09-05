import json
import os
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent.parent / "settings.json"

DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Downloads" / "VideoDL")

DEFAULT_SETTINGS = {
    "download_dir": DEFAULT_DOWNLOAD_DIR,
    "max_concurrent": 3,
    "default_quality": "best",
    "default_format": "mp4",
    "port": 7921,
}

def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                settings.update(data)
        except Exception as e:
            print(f"Error loading settings: {e}")
    # Ensure download directory exists
    try:
        os.makedirs(settings["download_dir"], exist_ok=True)
    except Exception:
        pass
    return settings

def save_settings(new_settings: dict) -> dict:
    settings = load_settings()
    for k in ["download_dir", "max_concurrent", "default_quality", "default_format", "port"]:
        if k in new_settings:
            val = new_settings[k]
            if k == "max_concurrent":
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

    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Error saving settings: {e}")

    return settings
