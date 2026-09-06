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
                    onBeforeRequest: { addListener: () => {} },
                    onBeforeSendHeaders: { addListener: () => {} },
                    onSendHeaders: { addListener: () => {} },
                    onHeadersReceived: { addListener: () => {} }
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
