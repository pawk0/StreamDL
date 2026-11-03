import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

import pytest
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad
from yt_dlp import YoutubeDL
from yt_dlp.downloader.external import FFmpegFD
from yt_dlp.downloader.hls import HlsFD

from server.engine import build_ydl_options
from server.task import DownloadTask


@pytest.mark.parametrize("explicit_iv", [False, True], ids=["sequence-iv", "explicit-iv"])
def test_native_hls_decrypts_segments_with_progress(tmp_path, monkeypatch, explicit_iv):
    key = bytes(range(16))
    iv = (7).to_bytes(16, "big")
    plaintext = [b"first encrypted media segment" * 25, b"second encrypted media segment" * 25]
    encrypted = [
        AES.new(key, AES.MODE_CBC, iv=iv if explicit_iv else (7 + index).to_bytes(16, "big")).encrypt(pad(data, 16))
        for index, data in enumerate(plaintext)
    ]
    iv_attribute = f",IV=0x{iv.hex()}" if explicit_iv else ""
    manifest = (
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:7\n"
        f'#EXT-X-KEY:METHOD=AES-128,URI="key.bin"{iv_attribute}\n'
        "#EXTINF:1,\n0.ts\n#EXTINF:1,\n1.ts\n#EXT-X-ENDLIST\n"
    ).encode()
    responses = {"/index.m3u8": manifest, "/key.bin": key, "/0.ts": encrypted[0], "/1.ts": encrypted[1]}
    received = []
    progress: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.path, self.headers))
            content = responses[self.path]
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format, *args):
            pass

    def reject_external_download(*args, **kwargs):
        pytest.fail("AES-128 streams must use native decryption, not delegate to FFmpeg")

    # Ensure a missing crypto dependency would exercise the problematic fallback.
    monkeypatch.setattr(FFmpegFD, "available", lambda: True)
    monkeypatch.setattr(FFmpegFD, "real_download", reject_external_download)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            headers = {"Accept-Language": "en-GB,en;q=0.9", "Referer": base + "/player", "User-Agent": "CapturedBrowser"}
            task = DownloadTask("aes-hls", base + "/index.m3u8", headers=headers)
            opts = build_ydl_options(task, str(tmp_path), progress.append, lambda d: None, custom_headers=headers)
            opts["proxy"] = ""
            output = tmp_path / "decrypted.mp4"
            with YoutubeDL(cast(Any, opts)) as ydl:
                # Upstream stubs describe old progress hooks and download return types.
                downloader = cast(Any, HlsFD(ydl, cast(Any, opts)))
                downloader.add_progress_hook(lambda event: progress.append(dict(event)))
                success, _ = downloader.download(str(output), {
                    "id": "aes-hls", "title": "Encrypted HLS", "url": task.url,
                    "ext": "mp4", "protocol": "m3u8_native",
                })
            assert success
            assert output.read_bytes() == b"".join(plaintext)
            assert any(event["status"] == "downloading" and event["downloaded_bytes"] > 0 for event in progress)
            assert progress[-1]["status"] == "finished"
            assert {path for path, _ in received} == set(responses)
            for _, actual_headers in received:
                assert actual_headers["Accept-Language"] == headers["Accept-Language"]
                assert actual_headers["Referer"] == headers["Referer"]
                assert actual_headers["User-Agent"] == headers["User-Agent"]
                assert actual_headers["Origin"] == base
        finally:
            server.shutdown()
            worker.join(timeout=2)
