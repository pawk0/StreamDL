import concurrent.futures
import json
import logging
import os
import time

from server.config import (
    clear_settings_cache,
    load_settings,
    match_provider,
    save_settings,
)


def test_provider_list_clearance_to_empty_list():
    """Verify that passing 'providers': [] successfully resets the list and persists across load_settings."""
    # Ensure baseline has providers
    initial = load_settings()
    assert len(initial.get("providers", [])) > 0

    # Explicitly clear providers list
    saved = save_settings({"providers": []})
    assert saved["providers"] == []

    # Verify disk persistence and reload
    reloaded = load_settings()
    assert reloaded["providers"] == []

    # Verify matching falls back to root domain without restoring DEFAULT_PROVIDERS
    pid, pname, limit = match_provider("https://dood.re/e/test12345")
    assert pid == "dood.re"
    assert pname == "dood.re"
    assert limit == reloaded.get("max_concurrent_per_provider", 1)


def test_provider_list_repopulation_after_clearance():
    """Verify that after clearing providers, new providers can still be added cleanly."""
    save_settings({"providers": []})
    assert load_settings()["providers"] == []

    custom = [
        {
            "id": "customhost",
            "name": "CustomHost",
            "patterns": ["*customhost.tv*"],
            "max_concurrent": 2,
        }
    ]
    saved = save_settings({"providers": custom})
    assert len(saved["providers"]) == 1
    assert saved["providers"][0]["id"] == "customhost"

    reloaded = load_settings()
    assert len(reloaded["providers"]) == 1
    assert reloaded["providers"][0]["id"] == "customhost"

    pid, pname, limit = match_provider("https://stream.customhost.tv/video.mp4")
    assert pid == "customhost"
    assert pname == "CustomHost"
    assert limit == 2


def test_settings_caching_and_external_invalidation(tmp_path, monkeypatch):
    """Verify that load_settings caches in memory and invalidates when file mtime changes."""
    test_file = tmp_path / "cache_test_settings.json"
    data = {"download_dir": str(tmp_path), "port": 17921, "max_concurrent": 4}
    test_file.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setenv("VIDEO_DL_SETTINGS_FILE", str(test_file))
    clear_settings_cache()

    first_load = load_settings()
    assert first_load["max_concurrent"] == 4

    # Calling again should return cached values
    second_load = load_settings()
    assert second_load["max_concurrent"] == 4

    # Mutating returned dictionary should not mutate internal cache
    first_load["max_concurrent"] = 99
    third_load = load_settings()
    assert third_load["max_concurrent"] == 4

    # Externally modify file and update mtime
    data["max_concurrent"] = 7
    # Note: On some filesystems mtime granularity is 1-2s, so we write and explicitly touch with future mtime
    new_mtime = time.time() + 5
    test_file.write_text(json.dumps(data), encoding="utf-8")
    os.utime(test_file, (new_mtime, new_mtime))

    reloaded = load_settings()
    assert reloaded["max_concurrent"] == 7


def test_save_settings_atomic_write(tmp_path, monkeypatch):
    """Verify that save_settings writes atomically to disk without leaving temp files behind."""
    test_file = tmp_path / "atomic_settings.json"
    monkeypatch.setenv("VIDEO_DL_SETTINGS_FILE", str(test_file))
    clear_settings_cache()

    save_settings({"max_concurrent": 5, "default_quality": "720p"})

    assert test_file.exists()
    content = json.loads(test_file.read_text(encoding="utf-8"))
    assert content["max_concurrent"] == 5
    assert content["default_quality"] == "720p"

    # Verify no leftover .tmp files
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_concurrent_settings_read_and_write(tmp_path, monkeypatch):
    """Verify that concurrent reads and writes from multiple threads do not race or corrupt data."""
    test_file = tmp_path / "concurrent_settings.json"
    monkeypatch.setenv("VIDEO_DL_SETTINGS_FILE", str(test_file))
    clear_settings_cache()

    save_settings({"max_concurrent": 1, "download_dir": str(tmp_path)})

    errors = []

    def writer(thread_id: int):
        try:
            for i in range(20):
                save_settings({
                    "max_concurrent": (thread_id % 5) + 1,
                    "default_quality": f"q_{thread_id}_{i}",
                })
        except Exception as e:  # noqa: BLE001 - capturing all thread errors for concurrent test assertions
            errors.append(f"Writer {thread_id} error: {e}")

    def reader(thread_id: int):
        try:
            for _ in range(30):
                s = load_settings()
                assert isinstance(s, dict)
                assert "download_dir" in s
                assert 1 <= s.get("max_concurrent", 1) <= 10
        except Exception as e:  # noqa: BLE001 - capturing all thread errors for concurrent test assertions
            errors.append(f"Reader {thread_id} error: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for i in range(4):
            futures.append(executor.submit(writer, i))
            futures.append(executor.submit(reader, i))
        concurrent.futures.wait(futures)

    assert errors == []

    # Final read must be valid JSON
    final = load_settings()
    assert isinstance(final["max_concurrent"], int)
    assert test_file.exists()
    assert json.loads(test_file.read_text(encoding="utf-8"))


def test_logging_used_instead_of_print(tmp_path, monkeypatch, caplog):
    """Verify that config errors log via logger.error rather than print()."""
    corrupt_file = tmp_path / "broken_settings.json"
    corrupt_file.write_text("invalid json{{", encoding="utf-8")
    monkeypatch.setenv("VIDEO_DL_SETTINGS_FILE", str(corrupt_file))
    monkeypatch.delenv("VIDEO_DL_PORT", raising=False)
    clear_settings_cache()

    with caplog.at_level(logging.ERROR, logger="video_dl.config"):
        settings = load_settings()
        assert settings["port"] == 7921

    assert any("Error loading settings" in record.message for record in caplog.records)
