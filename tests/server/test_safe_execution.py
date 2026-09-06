import uuid
from pathlib import Path

import pytest

from server.task import DownloadTask


def create_mock_task(manager, filepath: str | None = None) -> DownloadTask:
    task = DownloadTask(task_id=uuid.uuid4().hex[:8], url="https://example.com/test.mp4")
    task.status = "completed"
    task.filepath = filepath
    with manager._lock:
        manager.tasks[task.id] = task
        manager.task_order.append(task.id)
    return task


def test_open_file_path_traversal_blocked(client, manager, isolated_env, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: opened.append(args[1]))

    outside_dir = isolated_env["download_dir"].parent / "outside_dir"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "secret.mp4"
    outside_file.write_text("dummy")

    task = create_mock_task(manager, filepath=str(outside_file))

    res = client.post(f"/api/open-file/{task.id}")
    assert res.status_code == 403
    data = res.get_json()
    assert data["success"] is False
    assert "outside download directory" in data["error"].lower()
    assert len(opened) == 0


@pytest.mark.parametrize("unsafe_name", [
    "malware.exe",
    "script.bat",
    "payload.cmd",
    "exploit.ps1",
    "macro.vbs",
    "installer.msi",
    "reverse_shell.sh",
    "danger.js",
    "danger.py",
])
def test_open_file_unsafe_extension_blocked(client, manager, isolated_env, monkeypatch, unsafe_name: str):
    opened: list[str] = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: opened.append(args[1]))

    evil_file = isolated_env["download_dir"] / unsafe_name
    evil_file.write_text("evil contents")

    task = create_mock_task(manager, filepath=str(evil_file))

    res = client.post(f"/api/open-file/{task.id}")
    assert res.status_code == 403
    data = res.get_json()
    assert data["success"] is False
    assert "unsafe file extension" in data["error"].lower()
    assert len(opened) == 0


def test_open_file_directory_target_rejected(client, manager, isolated_env, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: opened.append(args[1]))

    sub_dir = isolated_env["download_dir"] / "subfolder.mp4"
    sub_dir.mkdir(parents=True, exist_ok=True)

    task = create_mock_task(manager, filepath=str(sub_dir))

    res = client.post(f"/api/open-file/{task.id}")
    assert res.status_code in [400, 403]
    data = res.get_json()
    assert data["success"] is False
    assert len(opened) == 0


@pytest.mark.parametrize("media_name", [
    "video.mp4",
    "movie.mkv",
    "stream.webm",
    "audio.mp3",
    "track.m4a",
    "subtitles.srt",
    "subtitles.vtt",
])
def test_open_file_safe_media_allowed(client, manager, isolated_env, monkeypatch, media_name: str):
    opened: list[str] = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: opened.append(args[1]))

    media_file = isolated_env["download_dir"] / media_name
    media_file.write_text("media contents")

    task = create_mock_task(manager, filepath=str(media_file))

    res = client.post(f"/api/open-file/{task.id}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert len(opened) == 1
    assert Path(opened[0]).resolve() == media_file.resolve()


def test_open_folder_traversal_blocked(client, isolated_env, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: opened.append(args[1]))

    res = client.post(
        "/api/open-folder",
        json={"folder": "../../.."},
    )
    assert res.status_code == 403
    data = res.get_json()
    assert data["success"] is False
    assert "outside download directory" in data["error"].lower()
    assert len(opened) == 0


def test_open_folder_file_target_rejected(client, isolated_env, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: opened.append(args[1]))

    file_target = isolated_env["download_dir"] / "test_file.txt"
    file_target.write_text("not a folder")

    res = client.post(
        "/api/open-folder",
        json={"folder": "test_file.txt"},
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "not a directory" in data["error"].lower()
    assert len(opened) == 0


def test_open_folder_subfolder_success(client, isolated_env, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: opened.append(args[1]))

    sub = isolated_env["download_dir"] / "season1"
    sub.mkdir(parents=True, exist_ok=True)

    res = client.post(
        "/api/open-folder",
        json={"folder": "season1"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert len(opened) == 1
    assert Path(opened[0]).resolve() == sub.resolve()
