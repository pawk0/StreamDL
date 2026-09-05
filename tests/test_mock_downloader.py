import os
import time
from unittest.mock import MagicMock, patch
import pytest

from server.downloader import (
    DownloadManager,
    DownloadTask,
    format_bytes,
    format_eta,
    sanitize_filename,
    is_generic_title,
    is_doodstream_url,
    resolve_doodstream,
)


class MockYoutubeDL:
    """Mock yt_dlp.YoutubeDL for simulating downloads and hooks."""

    def __init__(self, opts=None):
        self.opts = opts or {}
        MockYoutubeDL.last_instance = self
        MockYoutubeDL.all_instances.append(self)

    all_instances = []
    last_instance = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def extract_info(self, url, download=True):
        if getattr(self, "simulate_error", None):
            raise Exception(self.simulate_error)

        # Execute progress hooks
        progress_hooks = self.opts.get("progress_hooks", [])
        postprocessor_hooks = self.opts.get("postprocessor_hooks", [])

        if download:
            # 1. downloading hook
            for hook in progress_hooks:
                hook({
                    "status": "downloading",
                    "downloaded_bytes": 5000000,
                    "total_bytes": 10000000,
                    "speed": 1048576,
                    "eta": 5,
                    "filename": "mock_video.mp4",
                })

            # 2. finished progress hook
            for hook in progress_hooks:
                hook({
                    "status": "finished",
                    "filename": "mock_video.mp4",
                })

            # 3. finished postprocessor hook
            for hook in postprocessor_hooks:
                hook({
                    "status": "finished",
                    "filepath": "C:\\downloads\\mock_video.mp4" if os.name == "nt" else "/downloads/mock_video.mp4",
                })

            return {
                "id": "123",
                "title": "Mock Video Title",
                "thumbnail": "https://example.com/thumb.jpg",
                "_filename": "C:\\downloads\\mock_video.mp4" if os.name == "nt" else "/downloads/mock_video.mp4",
            }
        else:
            return {
                "id": "123",
                "title": "Mock Video Title",
                "thumbnail": "https://example.com/thumb.jpg",
            }


@pytest.fixture(autouse=True)
def reset_mock_ydl():
    MockYoutubeDL.all_instances.clear()
    MockYoutubeDL.last_instance = None


# =========================================================================
# Unit Tests for Helper Functions
# =========================================================================

def test_format_bytes():
    assert format_bytes(None) == "0 B"
    assert format_bytes(0) == "0 B"
    assert format_bytes(-10) == "0 B"
    assert format_bytes(500) == "500.0 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1024 * 1024 * 5) == "5.0 MB"
    assert format_bytes(1024 ** 3 * 2.5) == "2.5 GB"
    assert format_bytes(1024 ** 4 * 1.5) == "1.5 TB"
    assert format_bytes(1024 ** 5 * 3) == "3.0 PB"


def test_format_eta():
    assert format_eta(None) == "--:--"
    assert format_eta(-5) == "--:--"
    assert format_eta(0) == "00:00"
    assert format_eta(45) == "00:45"
    assert format_eta(75) == "01:15"
    assert format_eta(3665) == "01:01:05"


def test_sanitize_filename():
    assert sanitize_filename("") == "video"
    assert sanitize_filename(None) == "video"
    assert sanitize_filename('A/B\\C:D*E?F"G<H>I|J') == "ABCDEFGHIJ"
    assert sanitize_filename("  my video title.  ") == "my video title"
    long_name = "x" * 200
    assert len(sanitize_filename(long_name, max_length=50)) == 50


def test_is_generic_title():
    assert is_generic_title(None) is True
    assert is_generic_title("") is True
    assert is_generic_title("   ") is True
    assert is_generic_title("master") is True
    assert is_generic_title("index") is True
    assert is_generic_title("manifest") is True
    assert is_generic_title("playlist") is True
    assert is_generic_title("video") is True
    assert is_generic_title("fetching info...") is True
    assert is_generic_title("undefined") is True
    assert is_generic_title("master-stream-1080p") is True
    assert is_generic_title("index-f1-v1-a1") is True
    assert is_generic_title("Real Video Title") is False


def test_is_doodstream_url():
    assert is_doodstream_url("") is False
    assert is_doodstream_url(None) is False
    assert is_doodstream_url("https://youtube.com/watch?v=123") is False
    assert is_doodstream_url("https://dood.to/e/abcdef123456") is True
    assert is_doodstream_url("https://doodstream.com/d/xyz") is True
    assert is_doodstream_url("https://dood.video/e/xyz") is True


def test_resolve_doodstream_success(monkeypatch):
    embed_url = "https://dood.to/e/abcd1234efgh"
    fake_html = (
        '<html><script src="/pass_md5/xyz12345"></script>'
        '<script>makePlay("xyz"); var token="token9876";</script></html>'
    )
    fake_stream_prefix = "https://stream.dood.to/video/"

    def mock_urlopen(req, timeout=12):
        class MockResp:
            def __init__(self, data):
                self.data = data

            def read(self):
                return self.data.encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        if "/pass_md5/" in req.full_url:
            return MockResp(fake_stream_prefix)
        return MockResp(fake_html)

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    resolved = resolve_doodstream(embed_url, {"X-Custom": "header"})
    assert resolved is not None
    direct_url, headers = resolved
    assert direct_url.startswith("https://stream.dood.to/video/")
    assert "token=token9876" in direct_url
    assert headers["User-Agent"] is not None
    assert headers["X-Custom"] == "header"


def test_resolve_doodstream_failure(monkeypatch):
    def mock_urlopen_fail(req, timeout=12):
        raise Exception("Network error")

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_fail)
    assert resolve_doodstream("https://dood.to/e/abcd") is None


# =========================================================================
# Mock yt-dlp Execution Tests
# =========================================================================

def test_mock_ytdlp_successful_download(manager, monkeypatch):
    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYoutubeDL)

    task = manager.add_task(
        url="https://example.com/video1",
        title="Custom Video Name",
        quality="1080p",
        fmt="mp4"
    )

    manager._execute_download(task)

    assert task.status == "completed"
    assert task.progress == 100.0
    assert task.filename == "mock_video.mp4"
    assert task.filepath is not None
    assert task.completed_at is not None

    instance = MockYoutubeDL.last_instance
    assert instance is not None
    assert "bestvideo[height<=1080]" in instance.opts["format"]
    assert instance.opts["merge_output_format"] == "mp4"


def test_mock_ytdlp_extract_title_override_generic(manager, monkeypatch):
    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYoutubeDL)

    # Task starts with generic title
    task = manager.add_task(
        url="https://example.com/stream.m3u8",
        title="master",
        quality="best",
        fmt="mp4"
    )

    manager._execute_download(task)

    assert task.status == "completed"
    assert task.title == "Mock Video Title"
    assert task.thumbnail == "https://example.com/thumb.jpg"


def test_mock_ytdlp_quality_audio(manager, monkeypatch):
    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYoutubeDL)

    task = manager.add_task(
        url="https://example.com/audio1",
        quality="audio",
        fmt="mp3"
    )

    manager._execute_download(task)

    assert task.status == "completed"
    instance = MockYoutubeDL.last_instance
    assert instance.opts["format"] == "bestaudio/best"
    assert instance.opts["postprocessors"][0]["key"] == "FFmpegExtractAudio"
    assert instance.opts["postprocessors"][0]["preferredcodec"] == "mp3"


def test_mock_ytdlp_quality_720p_and_480p(manager, monkeypatch):
    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYoutubeDL)

    t720 = manager.add_task(url="https://example.com/v720", quality="720p", fmt="mkv")
    manager._execute_download(t720)
    assert "height<=720" in MockYoutubeDL.last_instance.opts["format"]
    assert MockYoutubeDL.last_instance.opts["merge_output_format"] == "mkv"

    t480 = manager.add_task(url="https://example.com/v480", quality="480p", fmt="mp4")
    manager._execute_download(t480)
    assert "height<=480" in MockYoutubeDL.last_instance.opts["format"]


def test_mock_ytdlp_custom_headers(manager, monkeypatch):
    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYoutubeDL)

    task = manager.add_task(
        url="https://example.com/video_with_headers",
        headers={"Referer": "https://source.com/", "User-Agent": "CustomUA"}
    )

    manager._execute_download(task)

    instance = MockYoutubeDL.last_instance
    assert instance.opts["http_headers"]["Referer"] == "https://source.com/"
    assert instance.opts["http_headers"]["User-Agent"] == "CustomUA"


def test_mock_ytdlp_hls_fragments_progress(manager, monkeypatch):
    class FragmentMockYDL(MockYoutubeDL):
        def extract_info(self, url, download=True):
            if download:
                for hook in self.opts.get("progress_hooks", []):
                    hook({
                        "status": "downloading",
                        "fragment_index": 7,
                        "fragment_count": 10,
                        "speed": 524288,
                        "eta": 15,
                    })
                    hook({
                        "_percent_str": " 75.0%",
                        "status": "downloading",
                        "speed": 524288,
                        "eta": 12,
                    })
            return {"title": "Fragment Video", "_filename": "fragment.mp4"}

    monkeypatch.setattr("yt_dlp.YoutubeDL", FragmentMockYDL)

    task = manager.add_task(url="https://example.com/live.m3u8")
    manager._execute_download(task)

    assert task.status == "completed"
    assert task.progress == 100.0


def test_mock_ytdlp_download_error(manager, monkeypatch):
    class FailingMockYDL(MockYoutubeDL):
        def extract_info(self, url, download=True):
            raise Exception("HTTP Error 404: Not Found")

    monkeypatch.setattr("yt_dlp.YoutubeDL", FailingMockYDL)

    task = manager.add_task(url="https://example.com/nonexistent")
    manager._execute_download(task)

    assert task.status == "failed"
    assert "404" in task.error_message
    assert task.completed_at is not None


def test_mock_ytdlp_cancellation_during_download(manager, monkeypatch):
    class CancelOnProgressYDL(MockYoutubeDL):
        def extract_info(self, url, download=True):
            if download:
                task.cancel_requested = True
                for hook in self.opts.get("progress_hooks", []):
                    hook({"status": "downloading"})
            return {}

    monkeypatch.setattr("yt_dlp.YoutubeDL", CancelOnProgressYDL)

    task = manager.add_task(url="https://example.com/cancel_test")
    manager._execute_download(task)

    assert task.status == "cancelled"
    assert task.completed_at is not None


def test_mock_ytdlp_requested_downloads_filename_detection(manager, monkeypatch):
    class RequestedDownloadsYDL(MockYoutubeDL):
        def extract_info(self, url, download=True):
            if download:
                return {
                    "title": "Multi Format",
                    "requested_downloads": [{"_filename": "output_merged.mp4"}],
                }
            return {"title": "Multi Format"}

    monkeypatch.setattr("yt_dlp.YoutubeDL", RequestedDownloadsYDL)

    task = manager.add_task(url="https://example.com/multi")
    manager._execute_download(task)

    assert task.status == "completed"
    assert task.filename == "output_merged.mp4"
    assert task.filepath.endswith("output_merged.mp4")


def test_mock_ytdlp_doodstream_resolution_integration(manager, monkeypatch):
    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYoutubeDL)

    def mock_resolve(url, headers):
        return ("https://resolved-stream.dood/video.mp4", {"X-Resolved": "1"})

    monkeypatch.setattr("server.downloader.resolve_doodstream", mock_resolve)

    task = manager.add_task(url="https://dood.to/e/sampleembed")
    manager._execute_download(task)

    assert task.status == "completed"
    instance = MockYoutubeDL.last_instance
    assert instance.opts["http_headers"].get("X-Resolved") == "1"


def test_resolve_doodstream_alt_regex(monkeypatch):
    embed_url = "https://dood.to/e/alt123"
    fake_html = "<html><script>$.get('/pass_md5/altpath123');</script></html>"

    def mock_urlopen(req, timeout=12):
        class MockResp:
            def read(self):
                return b"https://stream.dood.to/video/" if "/pass_md5/" in req.full_url else fake_html.encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return MockResp()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    res = resolve_doodstream(embed_url)
    assert res is not None
    assert res[0].startswith("https://stream.dood.to/video/")


def test_resolve_doodstream_no_match(monkeypatch):
    embed_url = "https://dood.to/e/nomatch"
    fake_html = "<html><body>No pass md5 here</body></html>"

    def mock_urlopen(req, timeout=12):
        class MockResp:
            def read(self):
                return fake_html.encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return MockResp()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    assert resolve_doodstream(embed_url) is None


def test_mock_ytdlp_cancellation_pre_download(manager, monkeypatch):
    class CancelPreDownloadYDL(MockYoutubeDL):
        def extract_info(self, url, download=True):
            if not download:
                task.cancel_requested = True
                return {"title": "Sample"}
            return {}

    monkeypatch.setattr("yt_dlp.YoutubeDL", CancelPreDownloadYDL)

    task = manager.add_task(url="https://example.com/cancel_pre")
    manager._execute_download(task)

    assert task.status == "cancelled"


def test_mock_ytdlp_postprocessor_cancellation(manager, monkeypatch):
    class CancelPostProcYDL(MockYoutubeDL):
        def extract_info(self, url, download=True):
            if download:
                task.cancel_requested = True
                for hook in self.opts.get("postprocessor_hooks", []):
                    hook({"status": "finished", "filepath": "final.mp4"})
            return {}

    monkeypatch.setattr("yt_dlp.YoutubeDL", CancelPostProcYDL)

    task = manager.add_task(url="https://example.com/cancel_post")
    manager._execute_download(task)

    assert task.status == "cancelled"


def test_mock_ytdlp_generic_title_fallback(manager, monkeypatch):
    class GenericTitleYDL(MockYoutubeDL):
        def extract_info(self, url, download=True):
            return {"title": "master", "_filename": "generic_output.mp4"}

    monkeypatch.setattr("yt_dlp.YoutubeDL", GenericTitleYDL)

    task = manager.add_task(url="https://example.com/generic_test", title="master")
    manager._execute_download(task)

    assert task.status == "completed"
    assert task.title == "generic_output.mp4"


def test_cancel_nonexistent_task(manager):
    assert manager.cancel_task("nonexistent-id-9999") is False


def test_mock_ytdlp_percent_str_exception(manager, monkeypatch):
    class MalformedPercentYDL(MockYoutubeDL):
        def extract_info(self, url, download=True):
            if download:
                for hook in self.opts.get("progress_hooks", []):
                    hook({"status": "downloading", "_percent_str": "invalid_number%"})
            return {"_filename": "done.mp4"}

    monkeypatch.setattr("yt_dlp.YoutubeDL", MalformedPercentYDL)

    task = manager.add_task(url="https://example.com/percent_err")
    manager._execute_download(task)
    assert task.status == "completed"

