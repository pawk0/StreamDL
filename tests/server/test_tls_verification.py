import email.message
import ssl
import urllib.error

import pytest
import yt_dlp

from server.config import (
    DEFAULT_SETTINGS,
    load_settings,
    match_provider,
    save_settings,
)
from server.engine import build_ydl_options, execute_download
from server.resolvers import resolve_doodstream
from server.task import DownloadTask
from server.utils import is_domain_or_subdomain, is_tls_cert_error

# =========================================================================
# 1. Exact Suffix Hostname Matching Tests
# =========================================================================

@pytest.mark.parametrize("hostname, domain, expected", [
    ("doodstream.com", "doodstream.com", True),
    ("sub.doodstream.com", "doodstream.com", True),
    ("cdn.video.doodstream.com", "doodstream.com", True),
    ("cloudatacdn.com", "cloudatacdn.com", True),
    ("node1.cloudatacdn.com", "cloudatacdn.com", True),
    # Suffix attacks and subdomains of other domains
    ("evil-doodstream.com.attacker.net", "doodstream.com", False),
    ("attacker-doodstream.com", "doodstream.com", False),
    ("doodstream.com.attacker.com", "doodstream.com", False),
    ("notdoodstream.com", "doodstream.com", False),
    ("evilcloudatacdn.com", "cloudatacdn.com", False),
    ("", "doodstream.com", False),
    (None, "doodstream.com", False),
])
def test_is_domain_or_subdomain(hostname, domain, expected):
    assert is_domain_or_subdomain(hostname, domain) is expected


def test_match_provider_exact_suffix_not_substring():
    """Verify that match_provider does not match attacker-controlled subdomains containing target string."""
    settings = {
        "providers": [
            {
                "id": "doodstream",
                "name": "Doodstream",
                "patterns": ["*doodstream.com*", "*cloudatacdn.com*"],
                "max_concurrent": 1,
            }
        ]
    }

    # Legitimate domains match
    pid1, pname1, _ = match_provider("https://doodstream.com/e/123", settings=settings)
    assert pid1 == "doodstream"
    assert pname1 == "Doodstream"

    pid2, _, _ = match_provider("https://sub.doodstream.com/e/123", settings=settings)
    assert pid2 == "doodstream"

    pid3, _, _ = match_provider("https://media.cloudatacdn.com/file", settings=settings)
    assert pid3 == "doodstream"

    # Attacker domains with substring injection must NOT match doodstream
    pid_evil1, _, _ = match_provider("https://evil-doodstream.com.attacker.net/video", settings=settings)
    assert pid_evil1 != "doodstream"

    pid_evil2, _, _ = match_provider("https://attacker-doodstream.com/video", settings=settings)
    assert pid_evil2 != "doodstream"

    pid_evil3, _, _ = match_provider("https://doodstream.com.attacker.com/video", settings=settings)
    assert pid_evil3 != "doodstream"


# =========================================================================
# 2. Config & Settings Persistence for tls_mode
# =========================================================================

def test_default_settings_tls_mode():
    assert DEFAULT_SETTINGS.get("tls_mode") == "auto"
    settings = load_settings()
    assert settings.get("tls_mode") == "auto"


@pytest.mark.parametrize("mode", ["auto", "strict", "permissive"])
def test_save_settings_tls_mode_valid(mode):
    updated = save_settings({"tls_mode": mode})
    assert updated.get("tls_mode") == mode
    reloaded = load_settings()
    assert reloaded.get("tls_mode") == mode


def test_save_settings_tls_mode_invalid_fallback():
    save_settings({"tls_mode": "invalid_mode"})
    reloaded = load_settings()
    assert reloaded.get("tls_mode") == "auto"


def test_save_settings_tls_mode_backwards_compatible_boolean():
    save_settings({"tls_verify": False})
    reloaded = load_settings()
    assert reloaded.get("tls_mode") == "permissive"

    save_settings({"tls_verify": True})
    reloaded = load_settings()
    assert reloaded.get("tls_mode") == "auto"


# =========================================================================
# 3. yt-dlp Options (build_ydl_options)
# =========================================================================

def test_build_ydl_options_tls_mode_auto():
    task = DownloadTask(task_id="t1", url="https://example.com/video.mp4")
    opts = build_ydl_options(
        task=task,
        download_dir="C:\\Downloads",
        progress_hook=lambda d: None,
        postprocessor_hook=lambda d: None,
        tls_mode="auto",
    )
    # In auto mode, TLS verification is enabled by default
    assert opts.get("nocheckcertificate") is False


def test_build_ydl_options_tls_mode_strict():
    task = DownloadTask(task_id="t2", url="https://example.com/video.mp4")
    opts = build_ydl_options(
        task=task,
        download_dir="C:\\Downloads",
        progress_hook=lambda d: None,
        postprocessor_hook=lambda d: None,
        tls_mode="strict",
    )
    assert opts.get("nocheckcertificate") is False


def test_build_ydl_options_tls_mode_permissive():
    task = DownloadTask(task_id="t3", url="https://example.com/video.mp4")
    opts = build_ydl_options(
        task=task,
        download_dir="C:\\Downloads",
        progress_hook=lambda d: None,
        postprocessor_hook=lambda d: None,
        tls_mode="permissive",
    )
    assert opts.get("nocheckcertificate") is True


# =========================================================================
# 4. Scheme Preservation (HTTP & HTTPS) in Resolvers
# =========================================================================

def test_resolve_doodstream_preserves_http_scheme(monkeypatch):
    embed_url = "http://dood.to/e/http123"
    requested_urls = []

    def mock_urlopen(req, timeout=12, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        requested_urls.append(url)

        class MockResp:
            def read(self):
                if "/pass_md5/" in url:
                    return b"http://stream.dood.to/video/"
                return b'<script src="/pass_md5/xyz"></script><script>token="t1";</script>'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return MockResp()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    resolved = resolve_doodstream(embed_url)
    assert resolved is not None
    direct_url, headers = resolved

    # Direct URL and Referer must retain http://
    assert direct_url.startswith("http://stream.dood.to/video/")
    assert headers["Referer"] == "http://dood.to/"
    # pass_url must have retained http://
    assert any(u.startswith("http://dood.to/pass_md5/") for u in requested_urls)


def test_resolve_doodstream_preserves_https_scheme(monkeypatch):
    embed_url = "https://dood.to/e/https123"
    requested_urls = []

    def mock_urlopen(req, timeout=12, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        requested_urls.append(url)

        class MockResp:
            def read(self):
                if "/pass_md5/" in url:
                    return b"https://stream.dood.to/video/"
                return b'<script src="/pass_md5/xyz"></script><script>token="t1";</script>'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return MockResp()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    resolved = resolve_doodstream(embed_url)
    assert resolved is not None
    direct_url, headers = resolved

    assert direct_url.startswith("https://stream.dood.to/video/")
    assert headers["Referer"] == "https://dood.to/"
    assert any(u.startswith("https://dood.to/pass_md5/") for u in requested_urls)


# =========================================================================
# 5. Scoped TLS Fallback in Resolvers (No Process-Wide Monkeypatch)
# =========================================================================

def test_process_wide_default_context_unmodified():
    """Verify that process-wide ssl._create_default_https_context is never overridden."""
    orig_fn = ssl._create_default_https_context
    assert ssl._create_default_https_context is orig_fn


def test_is_tls_cert_error_detection():
    cert_err = ssl.SSLCertVerificationError(1, "certificate verify failed: certificate has expired")
    assert is_tls_cert_error(cert_err) is True

    url_err = urllib.error.URLError(cert_err)
    assert is_tls_cert_error(url_err) is True

    url_err_msg = urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate")
    assert is_tls_cert_error(url_err_msg) is True

    msg = email.message.Message()
    http_404 = urllib.error.HTTPError("https://example.com", 404, "Not Found", msg, None)
    assert is_tls_cert_error(http_404) is False

    non_ssl_url_err = urllib.error.URLError("Connection refused")
    assert is_tls_cert_error(non_ssl_url_err) is False


def test_resolver_tls_fallback_on_matched_provider(monkeypatch, caplog):
    """In auto mode on matched provider domain, SSL cert error triggers scoped fallback with loud warning."""
    save_settings({"tls_mode": "auto"})
    embed_url = "https://dood.to/e/sslfallback"
    call_contexts = []

    def mock_urlopen(req, timeout=12, context=None):
        call_contexts.append(context)
        # First call with verified context raises SSLCertVerificationError
        if context is None or context.check_hostname:
            raise urllib.error.URLError(
                ssl.SSLCertVerificationError(1, "certificate verify failed: certificate has expired")
            )
        # Second call with unverified context succeeds
        class MockResp:
            def read(self):
                if "/pass_md5/" in req.full_url:
                    return b"https://stream.dood.to/video/"
                return b'<script src="/pass_md5/xyz"></script><script>token="t1";</script>'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return MockResp()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    with caplog.at_level("WARNING"):
        resolved = resolve_doodstream(embed_url)

    assert resolved is not None
    direct_url, _ = resolved
    assert direct_url.startswith("https://stream.dood.to/video/")
    # Loud warning was logged
    assert any("TLS certificate verification failed" in record.message for record in caplog.records)
    assert any("falling back to unverified TLS" in record.message for record in caplog.records)


def test_resolver_no_fallback_in_strict_mode(monkeypatch, caplog):
    """In strict mode, SSL cert error fails immediately without fallback even for providers."""
    save_settings({"tls_mode": "strict"})
    embed_url = "https://dood.to/e/strictssl"

    def mock_urlopen(req, timeout=12, context=None):
        raise urllib.error.URLError(
            ssl.SSLCertVerificationError(1, "certificate verify failed: certificate has expired")
        )

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    resolved = resolve_doodstream(embed_url)
    assert resolved is None


# =========================================================================
# 6. Engine Execution & Structured SSL Error Reporting
# =========================================================================

def test_execute_download_provider_ssl_retry_in_auto_mode(monkeypatch, caplog):
    """When a provider download fails with SSL cert error in auto mode, execute_download retries with nocheckcertificate."""
    save_settings({"tls_mode": "auto"})
    task = DownloadTask(task_id="task_ssl_retry", url="https://doodstream.com/e/retry123", title="SSL Video")
    attempt_opts = []

    class MockYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            attempt_opts.append(opts)
            self.params = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download=True):
            if not self.opts.get("nocheckcertificate"):
                raise yt_dlp.utils.DownloadError("Unable to download webpage: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired (_ssl.c:1000)")
            # With nocheckcertificate=True, download succeeds
            return {
                "title": "SSL Video",
                "_filename": "C:\\Downloads\\SSL Video.mp4",
                "requested_downloads": [{"_filename": "C:\\Downloads\\SSL Video.mp4"}],
            }

    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYoutubeDL)

    with caplog.at_level("WARNING"):
        execute_download(task, download_dir="C:\\Downloads")

    assert task.status == "completed"
    assert len(attempt_opts) == 2
    assert attempt_opts[0].get("nocheckcertificate") is False
    assert attempt_opts[1].get("nocheckcertificate") is True
    # Loud warning was logged
    assert any("TLS certificate verification failed" in record.message for record in caplog.records)
    assert any("Retrying with TLS verification bypassed" in record.message for record in caplog.records)


def test_execute_download_non_provider_ssl_fails_with_structured_error(monkeypatch):
    """When a non-provider download fails with SSL error in auto mode, fails with structured error guidance."""
    save_settings({"tls_mode": "auto"})
    task = DownloadTask(task_id="task_ssl_fail", url="https://random-unknown-site.org/video.mp4")

    class MockYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            self.params = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download=True):
            raise yt_dlp.utils.DownloadError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self signed certificate")

    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYoutubeDL)

    execute_download(task, download_dir="C:\\Downloads")

    assert task.status == "failed"
    assert task.error_message is not None
    assert "SSL_ERROR" in task.error_message
    assert "Try Permissive Mode" in task.error_message


def test_execute_download_strict_mode_fails_on_ssl(monkeypatch):
    """In strict mode, even provider domains fail on SSL error without retry."""
    save_settings({"tls_mode": "strict"})
    task = DownloadTask(task_id="task_strict_fail", url="https://doodstream.com/e/fail")
    attempts = 0

    class MockYoutubeDL:
        def __init__(self, opts):
            nonlocal attempts
            attempts += 1
            self.opts = opts
            self.params = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download=True):
            raise yt_dlp.utils.DownloadError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYoutubeDL)

    execute_download(task, download_dir="C:\\Downloads")

    assert task.status == "failed"
    assert attempts == 1
    assert task.error_message is not None
    assert "SSL_ERROR" in task.error_message
    assert "Try Permissive Mode" in task.error_message
