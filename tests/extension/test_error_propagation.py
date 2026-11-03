import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

EXTENSION_DIR = Path(__file__).resolve().parent.parent.parent / "extension"
UTILS_JS = (EXTENSION_DIR / "utils.js").read_text(encoding="utf-8")
BACKGROUND_JS = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def extension_page():
    """Launches headless Chromium and sets up extension environment with mock Chrome APIs."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Set up mock Chrome extension environment
        page.evaluate("""
            window.__mockStorage = {};
            window.__messageListeners = [];
            window.__contextMenus = [];
            window.__requestListeners = [];
            window.__responseListeners = [];
            window.chrome = {
                runtime: {
                    onMessage: {
                        addListener: (cb) => window.__messageListeners.push(cb)
                    },
                    onInstalled: { addListener: () => {} }
                },
                storage: {
                    local: {
                        get: (keys, cb) => {
                            const res = {};
                            for (const k of keys) {
                                if (window.__mockStorage[k] !== undefined) res[k] = window.__mockStorage[k];
                            }
                            if (cb) cb(res);
                            return Promise.resolve(res);
                        },
                        set: (obj, cb) => {
                            Object.assign(window.__mockStorage, obj);
                            if (cb) cb();
                            return Promise.resolve();
                        }
                    }
                },
                webRequest: {
                    onBeforeRequest: { addListener: cb => window.__requestListeners.push(cb) },
                    onBeforeSendHeaders: { addListener: () => {} },
                    onSendHeaders: { addListener: () => {} },
                    onHeadersReceived: { addListener: cb => window.__responseListeners.push(cb) }
                },
                tabs: {
                    onRemoved: { addListener: () => {} },
                    onUpdated: { addListener: () => {} }
                },
                contextMenus: {
                    create: (menu) => window.__contextMenus.push(menu),
                    onClicked: { addListener: () => {} }
                },
                action: {
                    setBadgeText: () => {},
                    setBadgeBackgroundColor: () => {}
                }
            };
        """)

        page.evaluate(UTILS_JS)
        page.evaluate(BACKGROUND_JS)

        yield page
        browser.close()


@pytest.mark.parametrize(
    ("initial_path", "next_path", "expected_path"),
    [
        ("master.m3u8?t=old", "master.m3u8?t=fresh", "master.m3u8?t=fresh"),
        ("master.m3u8?t=old", "720p.m3u8?t=child", "master.m3u8?t=old"),
        ("720p.m3u8?t=old", "master.m3u8?t=fresh", "master.m3u8?t=fresh"),
        ("720p.m3u8?t=old", "720p.m3u8?t=fresh", "720p.m3u8?t=fresh"),
        ("video.mp4?t=old", "video.mp4?t=fresh", "video.mp4?t=fresh"),
        ("master.m3u8?t=old", "master-final.m3u8?t=other", "master.m3u8?t=old"),
    ],
    ids=["refresh-master", "keep-master-over-child", "prefer-master", "refresh-child", "refresh-mp4", "keep-distinct-master"],
)
def test_stream_registration_refreshes_signed_urls(extension_page, initial_path, next_path, expected_path):
    result = extension_page.evaluate("""([initialPath, nextPath]) => {
        const tabId = window.__nextStreamTestTab = (window.__nextStreamTestTab || 100) + 1;
        const base = "https://cdn.example.com/video/";
        registerStream(tabId, base + initialPath, "", "", "https://player.example.com/", "Video", {"User-Agent": "Captured"});
        registerStream(tabId, base + nextPath);
        let streams;
        window.__messageListeners[0]({action: "GET_TAB_STREAMS", tabId}, {}, (response) => { streams = response.streams; });
        return streams;
    }""", [initial_path, next_path])
    assert len(result) == 1
    assert result[0]["url"] == "https://cdn.example.com/video/" + expected_path
    assert result[0]["headers"]["User-Agent"] == "Captured"
    assert result[0]["referer"] == "https://player.example.com/"


@pytest.mark.parametrize("late_source", ["response", "dom"])
def test_late_discovery_cannot_restore_old_token(extension_page, late_source):
    streams = extension_page.evaluate("""source => {
        const tabId = window.__nextStreamTestTab = (window.__nextStreamTestTab || 100) + 1;
        const oldUrl = "https://cdn.example.com/video/master.m3u8?t=old";
        const newUrl = "https://cdn.example.com/video/master.m3u8?t=new";
        const request = url => window.__requestListeners[0]({tabId, url, type: "media"});
        request(oldUrl);
        request(newUrl);
        if (source === "response") {
            window.__responseListeners[0]({tabId, url: oldUrl, type: "media",
                responseHeaders: [{name: "Content-Type", value: "application/vnd.apple.mpegurl"}]});
        } else {
            window.__messageListeners[0]({action: "REGISTER_DOM_MEDIA", url: oldUrl}, {tab: {id: tabId}}, () => {});
        }
        let result;
        window.__messageListeners[0]({action: "GET_TAB_STREAMS", tabId}, {}, r => result = r.streams);
        return result;
    }""", late_source)
    assert len(streams) == 1
    assert streams[0]["url"].endswith("?t=new")


def test_response_can_discover_unregistered_stream(extension_page):
    streams = extension_page.evaluate("""() => {
        const tabId = window.__nextStreamTestTab = (window.__nextStreamTestTab || 100) + 1;
        window.__responseListeners[0]({tabId, url: "https://cdn.example.com/video/stream",
            type: "xmlhttprequest", responseHeaders: [{name: "Content-Type", value: "video/mp4"}]});
        let result;
        window.__messageListeners[0]({action: "GET_TAB_STREAMS", tabId}, {}, r => result = r.streams);
        return result;
    }""")
    assert len(streams) == 1
    assert streams[0]["url"] == "https://cdn.example.com/video/stream"


def test_captured_language_reaches_download_api(extension_page):
    payloads = []

    def capture_download(route):
        payloads.append(route.request.post_data_json)
        route.fulfill(status=200, content_type="application/json", body='{"success": true}')

    extension_page.route("**/api/download", capture_download)
    result = extension_page.evaluate("""async () => {
        const headers = extractHeaders([
            {name: "accept-language", value: "en-GB,en;q=0.9"},
            {name: "User-Agent", value: "CapturedFirefox"},
            {name: "Referer", value: "https://player.example.com/"},
            {name: "Cookie", value: "session=original"}
        ]);
        return await sendDownloadRequest({url: "https://cdn.example.com/master.m3u8?t=original", headers});
    }""")
    assert result["success"] is True
    assert len(payloads) == 1
    assert payloads[0]["url"] == "https://cdn.example.com/master.m3u8?t=original"
    assert payloads[0]["headers"] == {
        "Accept-Language": "en-GB,en;q=0.9",
        "User-Agent": "CapturedFirefox",
        "Referer": "https://player.example.com/",
        "Origin": "https://player.example.com",
        "Cookie": "session=original",
    }


def test_send_download_duplicate_task_error_propagated(extension_page):
    """Verify that HTTP 400 with DuplicateTaskError JSON message is propagated verbatim."""
    duplicate_msg = "Task with name 'My Video' and URL 'https://example.com/vid' is already queued or downloading"

    extension_page.route(
        "**/api/download",
        lambda route: route.fulfill(
            status=400,
            content_type="application/json",
            body=json.dumps({"error": duplicate_msg, "success": False}),
        ),
    )

    result = extension_page.evaluate("""
        async () => {
            try {
                await sendDownloadRequest({
                    url: 'https://example.com/vid',
                    title: 'My Video'
                });
                return { success: true };
            } catch (err) {
                return { success: false, error: err.message };
            }
        }
    """)

    assert result["success"] is False
    assert duplicate_msg in result["error"]
    assert "Local server is offline" not in result["error"]


def test_send_download_validation_error_propagated(extension_page):
    """Verify that 400 validation error message is returned to the user."""
    validation_msg = "Invalid URL: must be http or https"

    extension_page.route(
        "**/api/download",
        lambda route: route.fulfill(
            status=400,
            content_type="application/json",
            body=json.dumps({"error": validation_msg, "success": False}),
        ),
    )

    result = extension_page.evaluate("""
        async () => {
            try {
                await sendDownloadRequest({
                    url: 'invalid://scheme'
                });
                return { success: true };
            } catch (err) {
                return { success: false, error: err.message };
            }
        }
    """)

    assert result["success"] is False
    assert validation_msg in result["error"]


def test_send_download_offline_server_error(extension_page):
    """Verify that actual network failure throws the server offline message."""
    extension_page.route(
        "**/api/download",
        lambda route: route.abort("failed"),
    )

    result = extension_page.evaluate("""
        async () => {
            try {
                await sendDownloadRequest({
                    url: 'https://example.com/offline'
                });
                return { success: true };
            } catch (err) {
                return { success: false, error: err.message };
            }
        }
    """)

    assert result["success"] is False
    assert "Local server is offline or unreachable" in result["error"]


def test_send_download_message_listener_error_propagation(extension_page):
    """Verify that SEND_DOWNLOAD runtime message listener returns { success: false, error: ... } with exact error."""
    custom_error = "Download rejected: provider concurrency limit exceeded"

    extension_page.route(
        "**/api/download",
        lambda route: route.fulfill(
            status=429,
            content_type="application/json",
            body=json.dumps({"error": custom_error, "success": False}),
        ),
    )

    result = extension_page.evaluate("""
        new Promise((resolve) => {
            const listener = window.__messageListeners.find(l => typeof l === 'function');
            listener(
                { action: 'SEND_DOWNLOAD', payload: { url: 'https://example.com/stream.m3u8' } },
                {},
                (response) => resolve(response)
            );
        })
    """)

    assert result["success"] is False
    assert custom_error in result["error"]
