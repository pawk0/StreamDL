import logging
import urllib.error
import urllib.request

import pytest

from server.engine import execute_download
from server.resolvers import (
    DEFAULT_RESOLVER_USER_AGENT,
    ResolverRegistry,
    default_resolver_registry,
    is_doodstream_embed_url,
    is_doodstream_url,
    register_resolver,
    resolve_doodstream,
    resolve_url,
    unregister_resolver,
)
from server.task import DownloadTask
from server.utils import is_valid_http_url


@pytest.fixture(autouse=True)
def reset_registry():
    """Ensure resolver registry is reset to its default state after each test."""
    yield
    default_resolver_registry.reset()


# =========================================================================
# 1. URL Validation Tests (SSRF & Scheme Defense)
# =========================================================================

@pytest.mark.parametrize("url, expected", [
    ("http://example.com", True),
    ("https://example.com/video.mp4", True),
    ("https://dood.to/e/abcdef123456", True),
    ("https://stream.dood.to:8080/video/part", True),
    ("file:///etc/passwd", False),
    ("javascript:alert(1)", False),
    ("ftp://files.example.com/movie.mp4", False),
    ("gopher://ancient.service/", False),
    ("data:text/html;base64,PHNjcmlwdD4=", False),
    ("/relative/path/pass_md5/xyz", False),
    ("", False),
    (None, False),
    (12345, False),  # pyrefly: ignore [bad-argument-type] - testing runtime type safety
])
def test_is_valid_http_url(url, expected):
    assert is_valid_http_url(url) is expected


# =========================================================================
# 2. Provider Decoupling & Doodstream URL Detection
# =========================================================================

@pytest.mark.parametrize("url, expected", [
    ("https://dood.to/e/abcd123", True),
    ("https://doodstream.com/d/xyz", True),
    ("https://dood.video/e/xyz", True),
    ("https://dood.re/e/xyz", True),
    ("https://dood.watch/e/xyz", True),
    ("https://cloudatacdn.com/video/123", True),
    ("https://youtube.com/watch?v=123", False),
    ("https://vimeo.com/123456", False),
    ("", False),
    (None, False),
])
def test_is_doodstream_url_provider_matching(url, expected):
    assert is_doodstream_url(url) is expected


def test_is_doodstream_url_dynamic_settings():
    """Verify is_doodstream_url respects custom patterns configured dynamically in settings."""
    custom_settings = {
        "providers": [
            {
                "id": "doodstream",
                "name": "Doodstream",
                "patterns": ["*custom-dood-mirror.org*"],
                "max_concurrent": 1,
            }
        ]
    }
    # Matches new custom mirror
    assert is_doodstream_url("https://custom-dood-mirror.org/e/123", settings=custom_settings) is True
    # Unlisted domain no longer matches
    assert is_doodstream_url("https://unlisted-domain.com/e/123", settings=custom_settings) is False


@pytest.mark.parametrize("url, expected", [
    ("https://dood.to/e/abcdef", True),
    ("https://dood.to/d/abcdef", True),
    ("https://dood.to/pass_md5/token123", False),
    ("https://stream.dood.to/video/abc?token=xyz", False),
    ("https://youtube.com/watch?v=123", False),
    ("", False),
    (None, False),
])
def test_is_doodstream_embed_url(url, expected):
    assert is_doodstream_embed_url(url) is expected


# =========================================================================
# 3. Generic Resolver Registry & Plugin System
# =========================================================================

def test_custom_resolver_registration_and_resolution():
    registry = ResolverRegistry()

    def mock_matcher(url: str) -> bool:
        return "custom-video-hub.com" in url

    def mock_resolver(url: str, headers: dict[str, str] | None = None) -> tuple[str, dict[str, str]] | None:
        return f"{url}/direct_stream.mp4", {"X-Resolved-By": "MockHub"}

    registry.register("mockhub", mock_matcher, mock_resolver, priority=100)
    assert registry.get("mockhub") is not None
    assert registry.find_resolver("https://custom-video-hub.com/watch?v=1") is not None
    assert registry.find_resolver("https://other.com/watch") is None

    result = registry.resolve("https://custom-video-hub.com/watch?v=1")
    assert result is not None
    direct_url, res_headers = result
    assert direct_url == "https://custom-video-hub.com/watch?v=1/direct_stream.mp4"
    assert res_headers["X-Resolved-By"] == "MockHub"


def test_resolver_priority_ordering():
    registry = ResolverRegistry()

    registry.register(
        "low_priority",
        lambda url: True,
        lambda url, headers=None: ("https://low.com/stream", {}),
        priority=10,
    )
    registry.register(
        "high_priority",
        lambda url: True,
        lambda url, headers=None: ("https://high.com/stream", {}),
        priority=90,
    )

    result = registry.resolve("https://any-url.com")
    assert result is not None
    assert result[0] == "https://high.com/stream"


def test_resolver_unregistration():
    registry = ResolverRegistry()
    registry.register("test_res", lambda url: True, lambda url, headers=None: ("https://test.com", {}))
    assert registry.get("test_res") is not None

    assert registry.unregister("test_res") is True
    assert registry.get("test_res") is None
    assert registry.resolve("https://test.com") is None


def test_global_registry_helpers():
    def dummy_matcher(url: str) -> bool:
        return "dummy-plugin.org" in url

    def dummy_resolver(url: str, headers: dict[str, str] | None = None) -> tuple[str, dict[str, str]] | None:
        return f"https://cdn.dummy-plugin.org/resolved_{url.split('/')[-1]}", {"X-Dummy": "True"}

    register_resolver("dummy_plugin", dummy_matcher, dummy_resolver, priority=50)

    res = resolve_url("https://dummy-plugin.org/item/42")
    assert res is not None
    assert res[0] == "https://cdn.dummy-plugin.org/resolved_42"
    assert res[1]["X-Dummy"] == "True"

    assert unregister_resolver("dummy_plugin") is True
    assert resolve_url("https://dummy-plugin.org/item/42") is None


# =========================================================================
# 4. User-Agent & Header Fidelity
# =========================================================================

def test_resolve_doodstream_custom_user_agent_propagation(monkeypatch):
    embed_url = "https://dood.to/e/testua123"
    captured_requests = []

    def mock_urlopen(req, timeout=12):
        captured_requests.append(req)

        class MockResp:
            def read(self):
                if "/pass_md5/" in req.full_url:
                    return b"https://stream.dood.to/video/"
                return (
                    b'<html><script src="/pass_md5/xyz"></script>'
                    b'<script>var token="tok123";</script></html>'
                )

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return MockResp()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    custom_ua = "Mozilla/5.0 (Windows NT 10.0) CustomClient/3.0"
    resolved = resolve_doodstream(embed_url, custom_headers={"User-Agent": custom_ua, "X-Auth": "secret"})

    assert resolved is not None
    direct_url, headers = resolved
    assert direct_url.startswith("https://stream.dood.to/video/")
    assert headers["User-Agent"] == custom_ua
    assert headers["X-Auth"] == "secret"
    assert headers["Referer"] == "https://dood.to/"

    # Verify both requests used caller's User-Agent
    assert len(captured_requests) == 2
    for r in captured_requests:
        assert r.get_header("User-agent") == custom_ua


def test_resolve_doodstream_case_insensitive_user_agent(monkeypatch):
    embed_url = "https://dood.to/e/caseua123"

    def mock_urlopen(req, timeout=12):
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

    # Lowercase 'user-agent'
    resolved = resolve_doodstream(embed_url, custom_headers={"user-agent": "LowerAgent/1.0"})
    assert resolved is not None
    _, headers = resolved
    assert headers["User-Agent"] == "LowerAgent/1.0"


def test_resolve_doodstream_default_user_agent(monkeypatch):
    embed_url = "https://dood.to/e/defua123"
    captured_requests = []

    def mock_urlopen(req, timeout=12):
        captured_requests.append(req)

        class MockResp:
            def read(self):
                if "/pass_md5/" in req.full_url:
                    return b"https://stream.dood.to/video/"
                return b'<script src="/pass_md5/xyz"></script>'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return MockResp()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    resolved = resolve_doodstream(embed_url)
    assert resolved is not None
    _, headers = resolved
    assert headers["User-Agent"] == DEFAULT_RESOLVER_USER_AGENT
    assert captured_requests[0].get_header("User-agent") == DEFAULT_RESOLVER_USER_AGENT


# =========================================================================
# 5. SSRF Defense & URL Validation in Doodstream Resolver
# =========================================================================

def test_resolve_doodstream_rejects_ssrf_stream_base(monkeypatch, caplog):
    """If pass_url returns a file:// or non-HTTP scheme, resolver must reject it and return None."""
    embed_url = "https://dood.to/e/ssrf123"

    def mock_urlopen(req, timeout=12):
        class MockResp:
            def read(self):
                if "/pass_md5/" in req.full_url:
                    # Malicious pass_md5 response attempting SSRF to local files
                    return b"file:///etc/passwd#"
                return b'<script src="/pass_md5/xyz"></script>'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return MockResp()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    with caplog.at_level(logging.WARNING, logger="video_dl.resolvers"):
        res = resolve_doodstream(embed_url)
        assert res is None
        assert any("invalid stream base URI" in record.message for record in caplog.records)


def test_resolve_doodstream_rejects_invalid_embed_url(caplog):
    with caplog.at_level(logging.WARNING, logger="video_dl.resolvers"):
        assert resolve_doodstream("file:///etc/passwd") is None
        assert resolve_doodstream("not-a-valid-url") is None
        assert any("invalid embed url" in record.message.lower() for record in caplog.records)


# =========================================================================
# 6. Narrow Exception Handling & Informative Logging
# =========================================================================

def test_resolve_doodstream_http_error(monkeypatch, caplog):
    def mock_urlopen(req, timeout=12):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)  # pyrefly: ignore [bad-argument-type] - mock HTTPError

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    with caplog.at_level(logging.WARNING, logger="video_dl.resolvers"):
        res = resolve_doodstream("https://dood.to/e/forbidden123")
        assert res is None
        assert any("HTTP 403" in record.message for record in caplog.records)


def test_resolve_doodstream_url_error(monkeypatch, caplog):
    def mock_urlopen(req, timeout=12):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    with caplog.at_level(logging.WARNING, logger="video_dl.resolvers"):
        res = resolve_doodstream("https://dood.to/e/refused123")
        assert res is None
        assert any("network error" in record.message.lower() for record in caplog.records)


def test_resolve_doodstream_timeout_error(monkeypatch, caplog):
    def mock_urlopen(req, timeout=12):
        raise TimeoutError("Request timed out after 12s")

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    with caplog.at_level(logging.WARNING, logger="video_dl.resolvers"):
        res = resolve_doodstream("https://dood.to/e/timeout123")
        assert res is None
        assert any("timeout" in record.message.lower() for record in caplog.records)


def test_resolve_doodstream_missing_pass_md5(monkeypatch, caplog):
    def mock_urlopen(req, timeout=12):
        class MockResp:
            def read(self):
                return b"<html><body>No pass md5 pattern here</body></html>"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return MockResp()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    with caplog.at_level(logging.WARNING, logger="video_dl.resolvers"):
        res = resolve_doodstream("https://dood.to/e/nopass123")
        assert res is None
        assert any("pass_md5" in record.message.lower() for record in caplog.records)


# =========================================================================
# 7. Engine Agnosticism & Resolver Registry Integration
# =========================================================================

def test_engine_executes_with_generic_resolver_registry(monkeypatch, tmp_path):
    """Verify execute_download resolves URLs via generic registry without doodstream imports."""
    passed_urls = []

    class MockYDL:
        def __init__(self, opts=None):
            self.opts = opts or {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download=True):
            passed_urls.append(url)
            return {
                "title": "Resolved Stream Video",
                "_filename": str(tmp_path / "stream.mp4"),
            }

    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYDL)

    # Register a custom plugin resolver
    def hub_matcher(url: str) -> bool:
        return "custom-engine-hub.io" in url

    def hub_resolver(url: str, headers: dict[str, str] | None = None) -> tuple[str, dict[str, str]] | None:
        return "https://cdn.custom-engine-hub.io/direct.m3u8", {"X-Engine-Plugin": "Active"}

    register_resolver("engine_hub", hub_matcher, hub_resolver)

    task = DownloadTask(
        task_id="engine_plugin_task",
        url="https://custom-engine-hub.io/play/999",
        title="master",
    )

    execute_download(task, download_dir=str(tmp_path))

    assert task.status == "completed"
    assert task.title == "Resolved Stream Video"
    assert "https://cdn.custom-engine-hub.io/direct.m3u8" in passed_urls


def test_engine_custom_resolver_arg(monkeypatch, tmp_path):
    """Verify execute_download supports an explicit resolver argument."""
    class MockYDL:
        def __init__(self, opts=None):
            self.opts = opts or {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download=True):
            return {"title": "Custom Resolver Video", "_filename": str(tmp_path / "custom.mp4")}

    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYDL)

    resolver_called = False

    def explicit_resolver(url: str, headers: dict[str, str] | None = None) -> tuple[str, dict[str, str]] | None:
        nonlocal resolver_called
        resolver_called = True
        return f"{url}_resolved", {"X-Custom-Resolver": "True"}

    task = DownloadTask(task_id="explicit_res_task", url="https://example.com/custom")
    execute_download(task, download_dir=str(tmp_path), resolver=explicit_resolver)

    assert task.status == "completed"
    assert resolver_called is True
