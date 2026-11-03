import json
import time

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import DEFAULT_PROVIDERS, DEFAULT_SETTINGS
from server.downloader import DownloadManager


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch, request):
    """
    Autouse fixture that runs for every test:
    1. Creates an isolated temporary settings.json and download folder.
    2. Sets VIDEO_DL_SETTINGS_FILE and VIDEO_DL_PORT (17921).
    3. Creates and shuts down a fresh manager for each test.
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

    manager = DownloadManager()
    monkeypatch.setattr(DownloadManager, "_instance", manager)
    if "client" in request.fixturenames and request.node.get_closest_marker("live") is None:
        def local_download(task):
            task.status = "downloading"
            while not task.pause_requested and not task.cancel_requested:
                time.sleep(0.01)
        monkeypatch.setattr("server.downloader.execute_download", local_download)
    manager.start()

    yield {
        "settings_file": test_settings_file,
        "download_dir": test_download_dir,
        "port": 17921,
        "manager": manager
    }

    manager.stop()


@pytest.fixture
def client(isolated_env):
    """Run ASGI lifespan while isolated settings still exist."""
    with TestClient(create_app(isolated_env["manager"])) as client:
        yield client


@pytest.fixture
def manager(isolated_env):
    """Provides the DownloadManager singleton."""
    return DownloadManager.get_instance()
