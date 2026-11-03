import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from server.config import save_settings
from server.downloader import DuplicateTaskError
from server.engine import execute_download
from server.task import DownloadTask


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline, "Worker did not reach expected state"
        time.sleep(0.01)


def test_pause_releases_slot_resume_bypasses_limits(manager, monkeypatch, client):
    save_settings({"max_concurrent": 1, "max_concurrent_per_provider": 1})
    runs = []

    def execute(task):
        runs.append(task.id)
        while not task.pause_requested and not task.cancel_requested:
            time.sleep(0.01)

    monkeypatch.setattr("server.downloader.execute_download", execute)
    first = manager.add_task("https://example.com/first.mp4", title="First")
    second = manager.add_task("https://example.com/second.mp4")
    third = manager.add_task("https://example.com/third.mp4")
    try:
        wait_until(lambda: first.id in runs)
        assert manager.pause_task(first.id)
        wait_until(lambda: first.status == "paused" and second.id in runs)
        assert first.id not in manager._active_threads
        assert first.id in manager._reserved_names
        assert third.status == "queued"
        assert manager.resume_task(first.id)
        wait_until(lambda: runs.count(first.id) == 2)
        assert first.status == "downloading"
        assert second.status == "downloading"
        assert third.status == "queued"
        assert len(manager._active_threads) == 2
        assert not manager.resume_task(first.id)
        assert client.post(f"/api/pause/{third.id}").status_code == 200
        assert third.status == "paused"
        assert client.post(f"/api/resume/{third.id}").status_code == 200
        wait_until(lambda: third.id in runs)
        assert third.status == "downloading"
    finally:
        for task in (first, second, third):
            manager.cancel_task(task.id)


@pytest.mark.parametrize("cancel", [False, True], ids=["resume-after-unwind", "cancel-during-unwind"])
def test_resume_during_pause_never_overlaps_workers(manager, monkeypatch, cancel):
    entered = threading.Event()
    release = threading.Event()
    runs = []

    def execute(task):
        runs.append(task.id)
        entered.set()
        assert release.wait(5)
        if len(runs) == 2:
            task.status = "completed"

    monkeypatch.setattr("server.downloader.execute_download", execute)
    task = manager.add_task("https://example.com/a.mp4")
    try:
        assert entered.wait(5)
        assert manager.pause_task(task.id)
        assert manager.resume_task(task.id)
        assert not manager.resume_task(task.id)
        assert task.to_dict()["status"] == "resuming"
        assert len(runs) == 1
        if cancel:
            manager.cancel_task(task.id)
        release.set()
        wait_until(lambda: task.id not in manager._active_threads)
        assert len(runs) == (1 if cancel else 2)
        assert task.status == ("cancelled" if cancel else "completed")
    finally:
        release.set()
        manager.cancel_task(task.id)


def test_queued_pause_duplicate_clear_and_cancel(client, manager, isolated_env):
    task = DownloadTask("paused", "https://example.com/a.mp4", title="Video")
    with manager._lock:
        manager.tasks[task.id] = task
        manager.task_order.append(task.id)
        task.status = "paused"
        task.pause_requested = True
    path = isolated_env["download_dir"] / "Video.mp4.part"
    path.write_bytes(b"partial")
    task.tracked_files.add(str(path))
    with pytest.raises(DuplicateTaskError):
        manager.add_task(task.url, title=task.title)
    manager.clear_finished()
    assert manager.get_task(task.id)["status"] == "paused"
    assert client.post(f"/api/pause/{task.id}").status_code == 409
    assert client.post(f"/api/cancel/{task.id}").status_code == 200
    assert task.status == "cancelled"
    assert not path.exists()
    assert client.post(f"/api/resume/{task.id}").status_code == 409


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("action", ["pause", "resume"])
def test_terminal_tasks_reject_controls(client, manager, status, action):
    task = DownloadTask("terminal", "https://example.com/a.mp4")
    task.status = status
    manager.tasks[task.id] = task
    assert client.post(f"/api/{action}/{task.id}").status_code == 409
    assert client.post(f"/api/{action}/missing").status_code == 409
    assert task.status == status


def test_pause_before_engine_start(monkeypatch, isolated_env):
    task = DownloadTask("startup", "https://example.com/a.mp4")
    task.pause_requested = True
    monkeypatch.setattr("server.engine.yt_dlp.YoutubeDL", lambda *_: pytest.fail("Paused task started"))
    execute_download(task, str(isolated_env["download_dir"]))
    assert task.status == "pausing"
    assert task.started_at is None
    assert task.completed_at is None


@pytest.mark.parametrize("supports_range", [True, False], ids=["resume-range", "restart-no-range"])
def test_http_partial_download_resumes_or_restarts(monkeypatch, isolated_env, supports_range):
    """Exercise real yt-dlp against loopback only, with and without HTTP Range support."""
    payload = bytes(range(256)) * 2048
    ranges = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()

        def do_GET(self):
            requested = self.headers.get("Range")
            ranges.append(requested)
            start = int(requested.split("=")[1].split("-")[0]) if requested and supports_range else 0
            self.send_response(206 if start else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(payload) - start))
            if start:
                self.send_header("Content-Range", f"bytes {start}-{len(payload)-1}/{len(payload)}")
            self.end_headers()
            try:
                self.wfile.write(payload[start:])
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    from server.engine import build_ydl_options

    task = DownloadTask("range", f"http://127.0.0.1:{server.server_port}/video.mp4", title="Video")
    pause_once = True

    def options(**kwargs):
        opts = build_ydl_options(**kwargs)
        original = opts["progress_hooks"][0]

        def hook(data):
            nonlocal pause_once
            original(data)
            if pause_once and data.get("downloaded_bytes", 0) > 0:
                pause_once = False
                task.pause_requested = True
                original(data)

        opts["progress_hooks"] = [hook]
        return opts

    monkeypatch.setattr("server.engine.build_ydl_options", options)
    directory = isolated_env["download_dir"]
    try:
        execute_download(task, str(directory), resolver=lambda *_: None)
        assert task.status == "pausing"
        partial = directory / "Video.mp4.part"
        assert 0 < partial.stat().st_size < len(payload)
        started_at = task.started_at
        task.pause_requested = False
        execute_download(task, str(directory), resolver=lambda *_: None)
        assert task.status == "completed", task.error_message
        assert task.started_at == started_at
        assert (directory / "Video.mp4").read_bytes() == payload
        assert not partial.exists()
        assert not (directory / "Video (1).mp4").exists()
        assert any(value and value != "bytes=0-" for value in ranges)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
