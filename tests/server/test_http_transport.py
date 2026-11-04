import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

import pytest
from yt_dlp import YoutubeDL
from yt_dlp.networking.common import Request
from yt_dlp.networking.exceptions import HTTPError

from server.diagnostics import (
    YtdlpLogger,
    redact_message,
    redact_url,
    summarize_headers,
)
from server.engine import build_ydl_options, execute_download
from server.patches import apply_ytdlp_patches
from server.task import DownloadTask


@pytest.fixture
def media_server():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.path, self.headers))
            if self.path.startswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", "/master.m3u8?t=redirect-secret")
                self.end_headers()
                return
            # Reproduce a server that rejects even an empty language header.
            self.send_response(403 if "Accept-Language" in self.headers else 200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.end_headers()
            self.wfile.write(b"#EXTM3U\n")

        def log_message(self, format, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", received
        finally:
            server.shutdown()
            worker.join(timeout=2)


@pytest.mark.parametrize("path", ["/master.m3u8", "/chunk.ts", "/redirect"])
@pytest.mark.parametrize(
    ("headers", "request_headers", "expected"),
    [
        pytest.param({}, {}, None, id="default-absent"),
        pytest.param({"accept-language": ""}, {}, None, id="explicit-empty-absent"),
        pytest.param({"accept-language": "pl-PL"}, {}, "pl-PL", id="captured-preserved"),
        pytest.param({}, {"ACCEPT-LANGUAGE": "de-DE"}, "de-DE", id="extractor-override-preserved"),
    ],
)
def test_language_header_on_wire(media_server, tmp_path, path, headers, request_headers, expected):
    base, received = media_server
    opts = build_ydl_options(
        DownloadTask("wire-test", base + path), str(tmp_path), lambda d: None, lambda d: None,
        custom_headers={"Referer": base + "/player", "User-Agent": "CapturedBrowser/1.0", **headers},
    )
    opts["proxy"] = ""
    with YoutubeDL(cast(Any, opts)) as ydl:
        if expected is None:
            with ydl.urlopen(cast(Any, Request(base + path, headers=request_headers))) as response:
                assert response.status == 200
        else:
            with pytest.raises(HTTPError) as error:
                ydl.urlopen(cast(Any, Request(base + path, headers=request_headers)))
            assert error.value.status == 403
            error.value.close()
    assert received
    for _, actual in received:
        assert actual.get("Accept-Language") == expected
        assert actual["Referer"] == base + "/player"
        assert actual["Origin"] == base
        assert actual["User-Agent"] == "CapturedBrowser/1.0"


def test_unpatched_empty_header_is_transmitted(media_server, tmp_path, monkeypatch):
    from yt_dlp.networking.common import RequestHandler

    base, received = media_server
    # Demonstrate why checking YoutubeDL.params alone missed the original bug.
    monkeypatch.setattr(RequestHandler, "_get_headers", cast(Any, RequestHandler)._get_headers.__wrapped__)
    opts = build_ydl_options(DownloadTask("empty-wire", base), str(tmp_path), lambda d: None, lambda d: None)
    opts["proxy"] = ""
    with YoutubeDL(cast(Any, opts)) as ydl:
        with pytest.raises(HTTPError) as error:
            ydl.urlopen(base + "/master.m3u8")
        error.value.close()
    assert received[0][1].get("Accept-Language") == ""


def test_failed_download_diagnostics(media_server, tmp_path, caplog):
    base, received = media_server
    task = DownloadTask(
        "diagnostic-task", base + "/master.m3u8?t=stream-secret", headers={
            "Accept-Language": "pl-PL", "Cookie": "session=cookie-secret",
            "Referer": base + "/player?session=referer-secret", "X-Custom": "header-secret",
        },
    )
    with caplog.at_level(logging.DEBUG, logger="video_dl"):
        execute_download(task, str(tmp_path))
    assert task.status == "failed"
    assert "HTTP 403" in caplog.text
    assert "captured headers" in caplog.text
    assert "effective headers" in caplog.text
    assert "Accept-Language=present" in caplog.text
    assert "via requests" in caplog.text or "via urllib" in caplog.text
    assert "metadata pre-extraction failed" in caplog.text
    for secret in ("stream-secret", "cookie-secret", "referer-secret", "header-secret"):
        assert secret not in caplog.text
    assert received
    for _, actual in received:
        assert actual["Cookie"] == "session=cookie-secret"
        assert actual["Referer"] == base + "/player?session=referer-secret"
        assert actual["Origin"] == base
        assert actual["X-Custom"] == "header-secret"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://user:password@example.com/master.m3u8?t=secret#secret", "https://example.com/master.m3u8"),
        ("https://example.com/stream.ts", "https://example.com/stream.ts"),
        ("https://[invalid", "<invalid URL>"),
    ],
)
def test_redact_url(url, expected):
    assert redact_url(url) == expected


@pytest.mark.parametrize("message", [
    "GET https://user:password@example.com/master.m3u8?t=secret",
    "ERROR [generic] master.m3u8?t=secret&s=secret: HTTP 403",
    "[debug] ffmpeg command line: ffmpeg -headers 'Cookie: secret' -i stream",
    "[debug] ffmpeg command line: ffmpeg -cookies 'session=secret; path=/;' -i stream",
])
def test_redact_message(message):
    assert "secret" not in redact_message(message)
    assert "password" not in redact_message(message)


@pytest.mark.parametrize("name", ["Cookie", "Authorization", "X-Api-Key", "X-Custom"])
def test_unknown_header_values_are_redacted(name):
    assert summarize_headers({name: "secret"}) == {name: "<present>"}


@pytest.mark.parametrize("level", [logging.INFO, logging.DEBUG])
@pytest.mark.parametrize("message", [
    "[debug] transport details",
    "[generic] Downloading m3u8 information",
    "[http] HTTP 200 https://example.com/master.m3u8?t=secret",
])
def test_downloader_diagnostics_require_debug(caplog, level, message):
    with caplog.at_level(level, logger="video_dl"):
        YtdlpLogger("diagnostics").debug(message)
    assert bool(caplog.records) == (level == logging.DEBUG)
    assert "secret" not in caplog.text


@pytest.mark.parametrize("method, level", [("warning", logging.WARNING), ("error", logging.ERROR)])
def test_downloader_problems_remain_visible(caplog, method, level):
    with caplog.at_level(logging.INFO, logger="video_dl"):
        getattr(YtdlpLogger("problem"), method)("HTTP failure")
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == level


def test_transport_patch_is_idempotent():
    from yt_dlp.networking.common import RequestHandler

    patched = cast(Any, RequestHandler)._get_headers
    apply_ytdlp_patches()
    assert cast(Any, RequestHandler)._get_headers is patched
