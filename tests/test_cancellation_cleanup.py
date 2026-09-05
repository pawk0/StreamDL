import os
import time
import pytest
from server.task import DownloadTask
from server.cleanup import (
    cleanup_task_files,
    release_file_handles,
    remove_file_with_retry,
)
from server.config import save_settings
from tests.test_mock_downloader import MockYoutubeDL


def test_cleanup_task_files_removes_part_ytdl_and_frag(tmp_path):
    download_dir = str(tmp_path)
    save_settings({"download_dir": download_dir})

    # Create dummy files for "My Video"
    video_files = [
        "My Video.mp4.part",
        "My Video.mp4.ytdl",
        "My Video.mp4.part-Frag29.part",
        "My Video.mp4.part-Frag1.part",
        "My Video.f137.mp4.part",
        "My Video.f140.m4a.part",
        "My Video.temp.mp4",
    ]
    for fn in video_files:
        p = os.path.join(download_dir, fn)
        with open(p, "wb") as f:
            f.write(b"partial video data")

    # Create unrelated files that should NOT be deleted
    unrelated_files = [
        "Other Video.mp4.part",
        "Other Video.mp4.ytdl",
        "My Video Already Completed.mp4",
    ]
    for fn in unrelated_files:
        p = os.path.join(download_dir, fn)
        with open(p, "wb") as f:
            f.write(b"unrelated file data")

    # Set up task
    task = DownloadTask(
        task_id="test1234",
        url="https://example.com/video",
        title="My Video",
    )
    task.filename = "My Video.mp4"
    task.filepath = os.path.join(download_dir, "My Video.mp4")
    task.status = "cancelled"
    task.started_at = time.time()

    deleted = cleanup_task_files(task, download_dir)

    # Verify all "My Video" partial files were deleted
    for fn in video_files:
        p = os.path.join(download_dir, fn)
        assert not os.path.exists(p), f"Expected {fn} to be removed, but it still exists!"

    # Verify unrelated files remain intact
    for fn in unrelated_files:
        p = os.path.join(download_dir, fn)
        assert os.path.exists(p), f"Expected {fn} to be preserved, but it was deleted!"

    assert len(deleted) == len(video_files)


def test_release_file_handles_allows_locked_file_deletion(tmp_path):
    download_dir = str(tmp_path)
    locked_file = os.path.join(download_dir, "stream.mp4.part")

    # Open a file and intentionally leave stream open in Python memory
    f = open(locked_file, "wb")
    f.write(b"locked fragment data")
    f.flush()

    # On Windows, deleting an open file raises PermissionError
    if os.name == "nt":
        with pytest.raises(PermissionError):
            os.remove(locked_file)

    # Calling release_file_handles should close the handle and collect gc
    closed = release_file_handles(download_dir, [locked_file])
    assert closed >= 1 or f.closed

    # Now deletion must succeed
    assert remove_file_with_retry(locked_file) is True
    assert not os.path.exists(locked_file)


def test_mock_ytdlp_cancellation_cleans_up_disk_files(manager, tmp_path, monkeypatch):
    download_dir = str(tmp_path / "stream_downloads")
    os.makedirs(download_dir, exist_ok=True)
    save_settings({"download_dir": download_dir})

    class CancellingMockYDL(MockYoutubeDL):
        def extract_info(self, url, download=True):
            if download:
                # Simulate yt-dlp creating temporary partial and fragment files on disk
                target_base = os.path.join(download_dir, "Cancelling Stream.mp4")
                for suffix in [".part", ".ytdl", ".part-Frag29.part"]:
                    with open(target_base + suffix, "wb") as f:
                        f.write(b"data")

                task.cancel_requested = True
                for hook in self.opts.get("progress_hooks", []):
                    hook({
                        "status": "downloading",
                        "filename": target_base,
                        "tmpfilename": target_base + ".part",
                    })
            return {}

    monkeypatch.setattr("yt_dlp.YoutubeDL", CancellingMockYDL)

    task = manager.add_task(
        url="https://example.com/stream",
        title="Cancelling Stream"
    )

    manager._execute_download(task)

    assert task.status == "cancelled"
    assert task.completed_at is not None

    # Check that download directory has no leftover .part or .ytdl files
    remaining = os.listdir(download_dir)
    assert remaining == [], f"Expected download dir to be clean, found: {remaining}"


def test_cancel_task_method_and_clear_finished(manager, tmp_path):
    download_dir = str(tmp_path)
    save_settings({"download_dir": download_dir})

    task = manager.add_task(url="https://example.com/queued_video", title="Queued Video")
    # Simulate partial files created somehow
    part_path = os.path.join(download_dir, "Queued Video.mp4.part")
    with open(part_path, "wb") as f:
        f.write(b"temp")

    task.filename = "Queued Video.mp4"
    task.filepath = os.path.join(download_dir, "Queued Video.mp4")

    # Cancel queued task
    success = manager.cancel_task(task.id)
    assert success is True
    assert task.status == "cancelled"
    assert not os.path.exists(part_path)

    # Clear finished tasks
    manager.clear_finished()
    assert manager.get_task(task.id) is None


def test_real_ytdlp_hls_cancellation_cleans_up_and_unlocks(manager, tmp_path):
    """
    End-to-end integration test with real yt-dlp HlsFD downloading a multi-segment stream.
    Tests that cancelling mid-stream cleans up *.mp4.part, *.ytdl, and *.part-Frag*.part files,
    releases all Python handles, and leaves no locked or leftover files on disk.
    """
    import http.server
    import socketserver
    import threading

    server_dir = tmp_path / "mock_hls_server"
    server_dir.mkdir(parents=True, exist_ok=True)

    # Write dummy m3u8 playlist and segments
    m3u8 = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:5\n#EXT-X-MEDIA-SEQUENCE:0\n"
    for i in range(1, 6):
        m3u8 += f"#EXTINF:5.0,\nseg{i}.ts\n"
        with open(server_dir / f"seg{i}.ts", "wb") as sf:
            sf.write(b"0" * 400000)
    m3u8 += "#EXT-X-ENDLIST\n"

    with open(server_dir / "stream.m3u8", "w", encoding="utf-8") as mf:
        mf.write(m3u8)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(server_dir), **kwargs)

        def log_message(self, format, *args):
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
    port = httpd.server_address[1]
    server_th = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_th.start()

    download_dir = str(tmp_path / "hls_downloads")
    os.makedirs(download_dir, exist_ok=True)
    save_settings({"download_dir": download_dir})

    try:
        task = manager.add_task(
            url=f"http://127.0.0.1:{port}/stream.m3u8",
            title="Real HLS Cancellation Test",
            quality="best",
            fmt="mp4",
        )

        # Let the download start in background thread via manager
        download_thread = threading.Thread(target=manager._execute_download, args=(task,), daemon=True)
        download_thread.start()

        # Wait until task enters downloading status or partial files appear
        start_t = time.time()
        while time.time() - start_t < 5:
            if task.status == "downloading" and (len(os.listdir(download_dir)) > 0 or task.downloaded_bytes > 0):
                break
            time.sleep(0.05)

        # Cancel the task
        manager.cancel_task(task.id)

        # Wait for thread to finish
        download_thread.join(timeout=3.0)

        assert task.status == "cancelled"

        # Verify download directory has no leftover files
        remaining = os.listdir(download_dir)
        assert remaining == [], f"Expected download dir to be empty after cancellation, found: {remaining}"

    finally:
        httpd.shutdown()
        httpd.server_close()

