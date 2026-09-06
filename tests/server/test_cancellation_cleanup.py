import os
import time

import pytest

from server.cleanup import (
    cleanup_task_files,
    release_file_handles,
    remove_file_with_retry,
)
from server.config import save_settings
from server.task import DownloadTask
from tests.server.test_mock_downloader import MockYoutubeDL


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
    f = open(locked_file, "wb")  # noqa: SIM115 - intentionally kept unclosed to test handle release
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


def test_cancellation_does_not_interrupt_concurrent_downloads(tmp_path):
    """
    Cancelling one active download must NOT close open file handles of other
    concurrent downloads running in the same download directory.
    """
    download_dir = str(tmp_path)
    save_settings({"download_dir": download_dir})

    # Task A: cancelled task
    task_a = DownloadTask(task_id="task_a", url="https://example.com/a", title="Task A")
    task_a.filename = "Task A.mp4"
    task_a.filepath = os.path.join(download_dir, "Task A.mp4")
    task_a.tracked_files.add(os.path.join(download_dir, "Task A.mp4.part"))
    task_a.status = "cancelled"
    task_a.started_at = time.time()

    # Create Task A partial file
    task_a_part = os.path.join(download_dir, "Task A.mp4.part")
    with open(task_a_part, "wb") as fa:
        fa.write(b"data_a")

    # Task B: concurrent active download with an open file stream
    task_b_part = os.path.join(download_dir, "Concurrent Task B.mp4.part")
    concurrent_handle = open(task_b_part, "wb")  # noqa: SIM115 - intentionally kept open to verify concurrent handle preservation
    concurrent_handle.write(b"initial_data_b")
    concurrent_handle.flush()

    try:
        # Run cleanup for Task A
        deleted = cleanup_task_files(task_a, download_dir)

        # Task A files should be deleted
        assert not os.path.exists(task_a_part)
        assert task_a_part in deleted

        # Concurrent task's handle MUST still be open and writable
        assert not concurrent_handle.closed, "Concurrent task handle was closed by Task A cleanup!"
        # Writing to the concurrent handle must succeed and not raise 'write to closed file'
        concurrent_handle.write(b"more_data_b")
        concurrent_handle.flush()

        # Concurrent task's file must still exist
        assert os.path.exists(task_b_part)
    finally:
        concurrent_handle.close()


@pytest.mark.parametrize(
    "cancelled_name,similar_name",
    [
        ("2025.mp4", "2025_1.mp4"),
        ("2025.mp4", "2025_2.mp4"),
        ("2025.mp4", "2025.1.mp4"),
        ("2025.mp4", "2025.special.mp4"),
        ("2025.mp4", "2025.final.mp4"),
        ("2025.mp4", "2025 Episode 1.mp4"),
        ("2025.mp4", "2025-01.mp4"),
        ("2025.mp4", "202501.mp4"),
        ("Video.mp4", "Video 2.mp4"),
        ("Video.mp4", "Video.Season1.mp4"),
    ],
)
def test_cancellation_does_not_affect_files_with_similar_names(tmp_path, cancelled_name, similar_name):
    """
    Cancelling a download (e.g. 2025.mp4) must NOT close handles or delete
    files of similarly named downloads (e.g. 2025_1.mp4, 2025_2.mp4, 2025.1.mp4).
    """
    download_dir = str(tmp_path)
    save_settings({"download_dir": download_dir})

    base_title = os.path.splitext(cancelled_name)[0]
    task = DownloadTask(task_id="test_cancel", url=f"https://example.com/{base_title}", title=base_title)
    task.filename = cancelled_name
    task.filepath = os.path.join(download_dir, cancelled_name)
    task.status = "cancelled"
    task.started_at = time.time()

    # Create cancelled task partial files
    files_to_cancel = [
        os.path.join(download_dir, f"{cancelled_name}.part"),
        os.path.join(download_dir, f"{cancelled_name}.ytdl"),
        os.path.join(download_dir, f"{cancelled_name}.part-Frag2.part"),
    ]
    for f in files_to_cancel:
        task.tracked_files.add(f)
        with open(f, "wb") as h:
            h.write(b"cancelled_task_data")

    # Create similarly named active file and keep an open file handle
    similar_part = os.path.join(download_dir, f"{similar_name}.part")
    similar_handle = open(similar_part, "wb")  # noqa: SIM115 - intentionally kept open to verify handle preservation
    similar_handle.write(b"active_similar_data")
    similar_handle.flush()

    try:
        # Run cleanup on the cancelled task
        deleted = cleanup_task_files(task, download_dir)

        # Cancelled files must be removed
        for f in files_to_cancel:
            assert not os.path.exists(f), f"Expected {f} to be deleted!"
            assert f in deleted

        # Similarly named file MUST NOT be deleted
        assert os.path.exists(similar_part), f"Similar file {similar_name}.part was wrongly deleted!"
        assert similar_part not in deleted

        # Handle for similarly named task MUST still be open and writable
        assert not similar_handle.closed, f"Handle for {similar_name}.part was closed by cleanup!"

        similar_handle.write(b"_additional_bytes")
        similar_handle.flush()
    finally:
        similar_handle.close()


def test_cleanup_nonexistent_directory(tmp_path):
    task = DownloadTask("t_ghost", "https://example.com/v")
    assert cleanup_task_files(task, download_dir=str(tmp_path / "ghost_dir_123")) == []


def test_release_file_handles_empty():
    assert release_file_handles("dummy_dir", task_filepaths=[]) == 0
    assert release_file_handles("dummy_dir", task_filepaths=None) == 0


def test_cleanup_with_tracked_files(tmp_path):
    download_dir = str(tmp_path / "tracked_dir")
    os.makedirs(download_dir, exist_ok=True)
    task = DownloadTask("t_tracked", "https://example.com/tracked")
    p1 = os.path.join(download_dir, "frag1.part")
    with open(p1, "wb") as f:
        f.write(b"data")
    task.tracked_files.add(p1)
    task.status = "cancelled"
    deleted = cleanup_task_files(task, download_dir)
    assert p1 in deleted
    assert not os.path.exists(p1)

def test_task_direct_track_and_close_streams(tmp_path):
    """Verify DownloadTask directly tracks open stream descriptors and closes them."""
    test_file = str(tmp_path / "stream.part")
    f = open(test_file, "wb")  # noqa: SIM115
    f.write(b"test data")
    f.flush()

    task = DownloadTask("task_stream", "https://example.com/stream")
    task.register_stream(f)
    assert f in task.open_streams

    # Closing streams should close the file and empty open_streams
    closed_count = task.close_streams()
    assert closed_count == 1
    assert f.closed
    assert len(task.open_streams) == 0

    # Calling again on empty set returns 0 safely
    assert task.close_streams() == 0


def test_cleanup_task_files_with_tracked_stream_bypasses_gc_get_objects(tmp_path, monkeypatch):
    """
    Verify cleanup_task_files closes task-tracked streams directly without scanning gc.get_objects.
    """
    import gc

    download_dir = str(tmp_path)
    save_settings({"download_dir": download_dir})

    frag_file = os.path.join(download_dir, "Video.mp4.part")
    f = open(frag_file, "wb")  # noqa: SIM115
    f.write(b"in-flight data")
    f.flush()

    task = DownloadTask("t_gc_opt", "https://example.com/gc_opt", title="Video")
    task.filename = "Video.mp4"
    task.filepath = os.path.join(download_dir, "Video.mp4")
    task.status = "cancelled"
    task.tracked_files.add(frag_file)
    task.register_stream(f)

    # Monkeypatch gc.get_objects to fail if called
    def fail_on_gc_get_objects():
        pytest.fail("gc.get_objects() should NOT be called when task tracks open streams directly!")

    monkeypatch.setattr(gc, "get_objects", fail_on_gc_get_objects)

    deleted = cleanup_task_files(task, download_dir)
    assert frag_file in deleted
    assert not os.path.exists(frag_file)
    assert f.closed


def test_remove_file_with_retry_with_task_bypasses_gc_get_objects(tmp_path, monkeypatch):
    """
    Verify remove_file_with_retry with task avoids gc.get_objects() during retries.
    """
    import gc

    download_dir = str(tmp_path)
    test_file = os.path.join(download_dir, "locked_retry.part")

    f = open(test_file, "wb")  # noqa: SIM115
    f.write(b"data")
    f.flush()

    task = DownloadTask("t_retry", "https://example.com/retry")
    task.register_stream(f)

    gc_calls = []
    original_get_objects = gc.get_objects

    def tracked_get_objects():
        gc_calls.append(1)
        return original_get_objects()

    monkeypatch.setattr(gc, "get_objects", tracked_get_objects)

    success = remove_file_with_retry(test_file, max_retries=3, delay=0.01, task=task)
    assert success is True
    assert not os.path.exists(test_file)
    assert f.closed
    assert len(gc_calls) == 0, f"gc.get_objects was called {len(gc_calls)} time(s) during retries!"





