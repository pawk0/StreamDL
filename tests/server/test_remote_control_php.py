import http.server
import os
import threading

import yt_dlp
import yt_dlp.utils

from server.engine import execute_download
from server.patches import apply_ytdlp_patches
from server.task import DownloadTask
from server.utils import is_generic_title


def setup_module():
    """Ensure yt-dlp patch is active for tests."""
    apply_ytdlp_patches()


def test_smart_determine_ext_with_query_param():
    """Test that streaming endpoints with query params are correctly identified."""
    url = (
        "https://media.website.abc/remote_control.php?"
        "file=FxVpakCFzcoVHWDLGXIQTpsqrndyMaP-llDDG6aQ0B40jGuvW0md.mp4&acctoken=abc123xyz"
    )
    ext = yt_dlp.utils.determine_ext(url)
    assert ext == "mp4"

    # MKV in query param
    url_mkv = "https://cdn.example.com/stream.php?video=feature_film.mkv&token=999"
    assert yt_dlp.utils.determine_ext(url_mkv) == "mkv"

    # WebM in query param
    url_webm = "https://cdn.example.com/download.php?f=clip.webm"
    assert yt_dlp.utils.determine_ext(url_webm) == "webm"


def test_smart_determine_ext_rejects_unsafe_extensions_in_query():
    """Test that unsafe extensions in query params are not returned."""
    # Exe in query param must NOT be treated as valid media extension
    url_exe = "https://evil.example.com/get.php?file=malware.exe"
    assert yt_dlp.utils.determine_ext(url_exe, default_ext=None) is None  # pyrefly: ignore [bad-argument-type] - monkey-patched function accepts default_ext=None

    # Php in query param
    url_php = "https://evil.example.com/run.php?file=shell.php"
    assert yt_dlp.utils.determine_ext(url_php, default_ext=None) is None  # pyrefly: ignore [bad-argument-type] - monkey-patched function accepts default_ext=None


def test_smart_determine_ext_without_query_param():
    """Test that script endpoints without query params return default_ext."""
    url_bare = "https://media.website.abc/remote_control.php?token=xyz"
    assert yt_dlp.utils.determine_ext(url_bare, default_ext=None) is None  # pyrefly: ignore [bad-argument-type] - monkey-patched function accepts default_ext=None
    assert yt_dlp.utils.determine_ext(url_bare, default_ext="unknown_video") == "unknown_video"


def test_normal_media_urls_unaffected():
    """Test that standard media URLs continue to work as expected."""
    assert yt_dlp.utils.determine_ext("https://example.com/video.mp4") == "mp4"
    assert yt_dlp.utils.determine_ext("https://example.com/live/playlist.m3u8") == "m3u8"
    assert yt_dlp.utils.determine_ext("https://example.com/track.mp3") == "mp3"


def test_is_generic_title_remote_control():
    """Test that remote_control is recognized as generic title."""
    assert is_generic_title("remote_control") is True
    assert is_generic_title("Remote Control") is True
    assert is_generic_title("remote_control.php") is True
    assert is_generic_title("download") is True
    assert is_generic_title("My Awesome Holiday Video") is False


class MockMediaServer:
    def __init__(self, port=0):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_HEAD(handler_self):
                if handler_self.path.startswith("/redirect"):
                    handler_self.send_response(302)
                    handler_self.send_header(
                        "Location",
                        f"http://127.0.0.1:{self.port}/remote_control.php?file=sample_1080p.mp4&token=tok"
                    )
                    handler_self.end_headers()
                elif handler_self.path.startswith("/html_page"):
                    handler_self.send_response(200)
                    handler_self.send_header("Content-Type", "text/html; charset=utf-8")
                    handler_self.end_headers()
                else:
                    handler_self.send_response(200)
                    handler_self.send_header("Content-Type", "video/mp4")
                    handler_self.send_header("Content-Length", "256")
                    handler_self.end_headers()

            def do_GET(handler_self):
                if handler_self.path.startswith("/redirect"):
                    handler_self.send_response(302)
                    handler_self.send_header(
                        "Location",
                        f"http://127.0.0.1:{self.port}/remote_control.php?file=sample_1080p.mp4&token=tok"
                    )
                    handler_self.end_headers()
                elif handler_self.path.startswith("/html_page"):
                    handler_self.send_response(200)
                    handler_self.send_header("Content-Type", "text/html; charset=utf-8")
                    handler_self.end_headers()
                    handler_self.wfile.write(b"<html><body>Not a video</body></html>")
                else:
                    handler_self.send_response(200)
                    handler_self.send_header("Content-Type", "video/mp4")
                    handler_self.send_header("Content-Length", "256")
                    handler_self.end_headers()
                    handler_self.wfile.write(b"M" * 256)

            def log_message(handler_self, format, *args):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", port), Handler)
        self.port = self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever)
        self.thread.daemon = True

    def start(self):
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_remote_control_php_download_execution(tmp_path):
    """Integration test: execute_download handles remote_control.php and saves clean mp4."""
    server = MockMediaServer()
    server.start()
    try:
        url = f"http://127.0.0.1:{server.port}/remote_control.php?file=test_clip_720p.mp4&token=xyz123"
        task = DownloadTask(
            task_id="rc_task_1",
            url=url,
            title="Test Remote Control Video",
            quality="best",
            fmt="mp4"
        )
        download_dir = str(tmp_path / "downloads")
        os.makedirs(download_dir, exist_ok=True)

        execute_download(task, download_dir=download_dir)

        assert task.status == "completed"
        assert task.filepath is not None
        assert os.path.exists(task.filepath)
        assert task.filepath.endswith(".mp4")
        assert not task.filepath.endswith(".php")
        assert os.path.getsize(task.filepath) == 256
    finally:
        server.stop()


def test_redirect_to_remote_control_php_execution(tmp_path):
    """Integration test: execute_download follows redirect to remote_control.php and succeeds."""
    server = MockMediaServer()
    server.start()
    try:
        url = f"http://127.0.0.1:{server.port}/redirect/get_file/1/video.mp4/?v-acctoken=abc"
        task = DownloadTask(
            task_id="rc_task_2",
            url=url,
            title="Test Redirect Video",
            quality="best",
            fmt="mp4"
        )
        download_dir = str(tmp_path / "downloads")
        os.makedirs(download_dir, exist_ok=True)

        execute_download(task, download_dir=download_dir)

        assert task.status == "completed"
        assert task.filepath is not None
        assert os.path.exists(task.filepath)
        assert task.filepath.endswith(".mp4")
        assert not task.filepath.endswith(".php")
        assert os.path.getsize(task.filepath) == 256
    finally:
        server.stop()


def test_html_page_fails_gracefully(tmp_path):
    """Test that a non-media HTML page at a .php URL fails gracefully without unusual extension crash."""
    server = MockMediaServer()
    server.start()
    try:
        url = f"http://127.0.0.1:{server.port}/html_page.php"
        task = DownloadTask(
            task_id="rc_task_3",
            url=url,
            title="Non Video Page",
            quality="best",
            fmt="mp4"
        )
        download_dir = str(tmp_path / "downloads")
        os.makedirs(download_dir, exist_ok=True)

        execute_download(task, download_dir=download_dir)

        assert task.status == "failed"
        # Must not be the unusual extension safety error
        assert "unusual and will be skipped for safety reasons" not in (task.error_message or "")
    finally:
        server.stop()
