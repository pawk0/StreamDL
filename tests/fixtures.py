import json

import pytest

from server.app import app
from server.config import DEFAULT_PROVIDERS, DEFAULT_SETTINGS
from server.downloader import DownloadManager


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """
    Autouse fixture that runs for every test:
    1. Creates an isolated temporary settings.json and download folder.
    2. Sets VIDEO_DL_SETTINGS_FILE and VIDEO_DL_PORT (17921).
    3. Resets DownloadManager state before and after each test.
    4. Guarantees that production settings.json is never touched.
    """
    test_settings_file = tmp_path / "test_settings.json"
    test_download_dir = tmp_path / "downloads"
    test_download_dir.mkdir(parents=True, exist_ok=True)

    initial_settings = dict(DEFAULT_SETTINGS)
    initial_settings["download_dir"] = str(test_download_dir)
    initial_settings["providers"] = [dict(p) for p in DEFAULT_PROVIDERS]
    initial_settings["port"] = 17921

    with open(test_settings_file, "w", encoding="utf-8") as f:
        json.dump(initial_settings, f, indent=2)

    monkeypatch.setenv("VIDEO_DL_SETTINGS_FILE", str(test_settings_file))
    monkeypatch.setenv("VIDEO_DL_PORT", "17921")

    manager = DownloadManager.get_instance()
    with manager._lock:
        manager.tasks.clear()
        manager.task_order.clear()
        manager._active_threads.clear()
        manager._reserved_names.clear()

    yield {
        "settings_file": test_settings_file,
        "download_dir": test_download_dir,
        "port": 17921,
        "manager": manager
    }

    with manager._lock:
        manager.tasks.clear()
        manager.task_order.clear()
        manager._active_threads.clear()
        manager._reserved_names.clear()


@pytest.fixture
def client():
    """Provides a Flask test client."""
    return app.test_client()


@pytest.fixture
def manager():
    """Provides the DownloadManager singleton."""
    return DownloadManager.get_instance()
