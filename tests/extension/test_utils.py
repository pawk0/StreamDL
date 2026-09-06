from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import sync_playwright

from server.config import DEFAULT_PROVIDERS

EXTENSION_DIR = Path(__file__).resolve().parent.parent.parent / "extension"
UTILS_JS = (EXTENSION_DIR / "utils.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def browser_page():
    """Launches headless Chromium, collects V8 JS coverage, and injects mock Chrome storage."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Start V8 JavaScript coverage via Chrome DevTools Protocol
        cdp = page.context.new_cdp_session(page)
        cdp.send("Profiler.enable")
        cdp.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})

        # Inject Chrome mock storage environment
        page.evaluate("""
            window.__mockStorage = {};
            window.chrome = {
                runtime: {},
                storage: {
                    local: {
                        get: (keys, cb) => {
                            const result = {};
                            for (const k of keys) {
                                if (window.__mockStorage[k] !== undefined) {
                                    result[k] = window.__mockStorage[k];
                                }
                            }
                            if (cb) cb(result);
                            return Promise.resolve(result);
                        },
                        set: (obj, cb) => {
                            Object.assign(window.__mockStorage, obj);
                            if (cb) cb();
                            return Promise.resolve();
                        }
                    }
                }
            };
        """)

        # Evaluate utils.js
        page.evaluate(UTILS_JS)
        yield page

        # Collect and report V8 coverage
        cov_data = cdp.send("Profiler.takePreciseCoverage")
        cdp.send("Profiler.stopPreciseCoverage")
        cdp.send("Profiler.disable")

        for entry in cov_data.get("result", []):
            funcs = [f for f in entry.get("functions", []) if f.get("functionName")]
            if any(f["functionName"] == "analyzeStreamUrl" for f in funcs):
                total = len(funcs)
                covered = sum(1 for f in funcs if any(r["count"] > 0 for r in f["ranges"]))
                pct = (covered / total) * 100 if total else 0
                print(f"\n[Extension JS Coverage] utils.js functions: {covered}/{total} ({pct:.1f}%)")
                break

        browser.close()


@pytest.mark.parametrize(
    ("url", "expected_type", "expected_master", "expected_variant"),
    [
        ("https://cdn.example.com/video/master.m3u8", "HLS (.m3u8)", True, False),
        ("https://cdn.example.com/video/playlist.m3u8", "HLS (.m3u8)", True, False),
        ("https://cdn.example.com/video/index.m3u8", "HLS (.m3u8)", True, False),
        ("https://cdn.example.com/video/main.m3u8", "HLS (.m3u8)", True, False),
        ("https://cdn.example.com/video/manifest.m3u8", "HLS (.m3u8)", True, False),
        ("https://cdn.example.com/video/index-f2-v1-a1.m3u8", "HLS (.m3u8)", False, True),
        ("https://cdn.example.com/video/1080p.m3u8", "HLS (.m3u8)", False, True),
        ("https://cdn.example.com/video/720p.m3u8", "HLS (.m3u8)", False, True),
        ("https://cdn.example.com/video/chunklist.m3u8", "HLS (.m3u8)", False, True),
        ("https://cdn.example.com/video/rendition.m3u8", "HLS (.m3u8)", False, True),
        ("https://dood.video/d/xyz123", "Doodstream Video", True, False),
        ("https://doodstream.com/e/abc456", "Doodstream Video", True, False),
        ("https://dood.so/pass_md5/xyz", "Doodstream Video", True, False),
        ("https://player.org/remote_control.php?file=123", "Direct MP4 Stream", True, False),
        ("https://cdn.example.com/dash/stream.mpd", "DASH (.mpd)", True, False),
        ("https://cdn.example.com/files/movie.mp4", "MP4 Video", True, False),
        ("https://cdn.example.com/files/clip.webm", "WebM Video", True, False),
    ],
)
def test_analyze_stream_url_valid_streams(
    browser_page, url: str, expected_type: str, expected_master: bool, expected_variant: bool
):
    res: dict[str, Any] = browser_page.evaluate(
        "(url) => StreamDLUtils.analyzeStreamUrl(url)", url
    )
    assert res is not None, f"Expected valid stream info for {url}"
    assert res["type"] == expected_type
    assert res["isMaster"] is expected_master
    assert res["isVariant"] is expected_variant


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.example.com/hls/segment-1.ts",
        "https://cdn.example.com/hls/chunk_0.m4s",
        "https://cdn.example.com/audio/track.aac",
        "https://cdn.example.com/hls/seg-5-v1.ts",
        "https://cdn.example.com/hls/fragment.mp4",
        "https://cdn.example.com/thumbnails/preview.jpg",
        "https://cdn.example.com/icons/play.png",
        "https://cdn.example.com/subtitles/en.vtt",
        "https://cdn.example.com/styles/player.css",
        "https://cdn.example.com/scripts/bundle.js",
        "",
        None,
    ],
)
def test_analyze_stream_url_excluded_segments_and_assets(browser_page, url: str | None):
    res = browser_page.evaluate("(url) => StreamDLUtils.analyzeStreamUrl(url)", url)
    assert res is None


def test_get_stream_key_groups_variants(browser_page):
    key1 = browser_page.evaluate(
        "() => StreamDLUtils.getStreamKey('https://cdn.example.com/hls/live/master.m3u8')"
    )
    key2 = browser_page.evaluate(
        "() => StreamDLUtils.getStreamKey('https://cdn.example.com/hls/live/index-f1.m3u8')"
    )
    key3 = browser_page.evaluate(
        "() => StreamDLUtils.getStreamKey('https://cdn.example.com/hls/other/master.m3u8')"
    )
    assert key1 == "https://cdn.example.com/hls/live"
    assert key1 == key2
    assert key1 != key3


def test_extract_headers(browser_page):
    headers_input = [
        {"name": "referer", "value": "https://referer.example.com/watch"},
        {"name": "Origin", "value": "https://referer.example.com"},
        {"name": "USER-AGENT", "value": "Mozilla/5.0 TestBrowser"},
        {"name": "cookie", "value": "session=xyz123"},
        {"name": "accept", "value": "*/*"},
        {"name": "x-custom", "value": "ignore-me"},
    ]
    res = browser_page.evaluate(
        "(headers) => StreamDLUtils.extractHeaders(headers)", headers_input
    )
    assert res == {
        "Referer": "https://referer.example.com/watch",
        "Origin": "https://referer.example.com",
        "User-Agent": "Mozilla/5.0 TestBrowser",
        "Cookie": "session=xyz123",
    }


@pytest.mark.parametrize(
    ("referer", "expected_origin"),
    [
        ("https://player.example.com:8443/embed/video?id=1", "https://player.example.com:8443"),
        ("http://localhost:3000/test", "http://localhost:3000"),
        ("not-a-valid-url", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_derive_origin_from_referer(browser_page, referer: str | None, expected_origin: str):
    res = browser_page.evaluate(
        "(ref) => StreamDLUtils.deriveOriginFromReferer(ref)", referer
    )
    assert res == expected_origin


def test_provider_matching_parity(browser_page):
    providers_list = [dict(p) for p in DEFAULT_PROVIDERS]

    dood_provider = browser_page.evaluate(
        """([url, providers]) => StreamDLUtils.detectProvider(url, '', providers)""",
        ["https://doodstream.com/d/12345", providers_list],
    )
    assert dood_provider == "Doodstream"

    lulu_provider = browser_page.evaluate(
        """([url, providers]) => StreamDLUtils.detectProvider(url, '', providers)""",
        ["https://cdn-tnmr.org/video/index.m3u8", providers_list],
    )
    assert lulu_provider == "LuluStream"

    custom_providers = [
        *providers_list,
        {"id": "custom", "name": "Custom Provider", "patterns": ["*remote_control.php*"]},
    ]
    custom_match = browser_page.evaluate(
        """([url, providers]) => StreamDLUtils.detectProvider(url, '', providers)""",
        ["https://media.server.org/remote_control.php?token=abc", custom_providers],
    )
    assert custom_match == "Custom Provider"

    fallback = browser_page.evaluate(
        """([url, providers]) => StreamDLUtils.detectProvider(url, '', providers)""",
        ["https://cdn.sub.unknownsite.org/stream.m3u8", providers_list],
    )
    assert fallback == "unknownsite.org"


@pytest.mark.parametrize(
    ("raw_title", "expected_clean"),
    [
        ("Awesome Movie - SiteName", "Awesome Movie"),
        ("Documentary Part 1 | VideoHost", "Documentary Part 1"),
        ("Just A Normal Title", "Just A Normal Title"),
        ("", ""),
    ],
)
def test_clean_video_title(browser_page, raw_title: str, expected_clean: str):
    res = browser_page.evaluate(
        "(t) => StreamDLUtils.cleanVideoTitle(t)", raw_title
    )
    assert res == expected_clean


def test_extract_filename(browser_page):
    res1 = browser_page.evaluate(
        "() => StreamDLUtils.extractFilename('https://example.com/path/to/stream.m3u8?token=xyz')"
    )
    assert res1 == "stream.m3u8"

    res2 = browser_page.evaluate(
        "() => StreamDLUtils.extractFilename('https://example.com/')"
    )
    assert res2 == "stream"


def test_server_url_storage_configuration(browser_page):
    # Default without storage config
    browser_page.evaluate("() => { window.__mockStorage = {}; }")
    default_url = browser_page.evaluate("() => StreamDLUtils.getServerUrl()")
    assert default_url == "http://localhost:7921"

    # Set numeric port
    browser_page.evaluate("() => StreamDLUtils.setServerUrl(17921)")
    port_url = browser_page.evaluate("() => StreamDLUtils.getServerUrl()")
    assert port_url == "http://localhost:17921"

    # Set full custom URL with trailing slash
    browser_page.evaluate("() => StreamDLUtils.setServerUrl('http://127.0.0.1:8888/')")
    custom_url = browser_page.evaluate("() => StreamDLUtils.getServerUrl()")
    assert custom_url == "http://127.0.0.1:8888"


def test_format_stream_label(browser_page):
    providers_list = [dict(p) for p in DEFAULT_PROVIDERS]

    master_stream = {
        "url": "https://cdn-tnmr.org/video/master.m3u8",
        "isMaster": True,
        "referer": "https://lulustream.com/e/123",
    }
    label1 = browser_page.evaluate(
        "([s, p]) => StreamDLUtils.formatStreamLabel(s, p)",
        [master_stream, providers_list],
    )
    assert "⭐ [Master]" in label1
    assert "master.m3u8" in label1
    assert "LuluStream" in label1

    variant_stream = {
        "url": "https://example.com/hls/1080p.m3u8",
        "isMaster": False,
        "referer": "",
    }
    label2 = browser_page.evaluate(
        "([s, p]) => StreamDLUtils.formatStreamLabel(s, p)",
        [variant_stream, providers_list],
    )
    assert "⭐ [Master]" not in label2
    assert "1080p.m3u8" in label2
    assert "example.com" in label2

