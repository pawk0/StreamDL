import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

INDEX_HTML_PATH = Path(__file__).resolve().parent.parent.parent / "server" / "templates" / "index.html"
APP_JS_PATH = Path(__file__).resolve().parent.parent.parent / "server" / "static" / "js" / "app.js"
BASE_TEST_URL = "http://localhost:17921"


@pytest.fixture(scope="module")
def browser_context():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def test_dashboard_xss_sanitization(browser_context):
    page = browser_context.new_page()

    html_content = INDEX_HTML_PATH.read_text(encoding="utf-8")
    app_js = APP_JS_PATH.read_text(encoding="utf-8")

    # Set up mock queue response containing malicious XSS payloads across all user/remote-controlled fields
    malicious_tasks = [
        {
            "id": "task-downloading",
            "title": '<img src=x onerror="window.__xss_title = true"> Malicious Title',
            "url": '"><img src=x onerror="window.__xss_url = true">https://example.com/stream',
            "thumbnail": 'x" onerror="window.__xss_thumb = true"',
            "quality": "1080p",
            "format": "mp4",
            "status": "downloading",
            "downloaded_str": "10MB",
            "total_str": "100MB",
            "speed": "2MB/s",
            "eta": "45s",
            "progress": 10.0,
            "provider": '<img src=x onerror="window.__xss_provider = true">MaliciousProvider',
            "provider_id": "direct",
        },
        {
            "id": "task-failed",
            "title": "Failed Task",
            "url": "https://example.com/fail",
            "thumbnail": "javascript:window.__xss_js_url = true",
            "quality": "720p",
            "format": "mkv",
            "status": "failed",
            "error_message": '<img src=x onerror="window.__xss_error = true">Server Error',
            "progress": 0.0,
            "provider": "Direct",
            "provider_id": "direct",
        },
        {
            "id": "task-completed",
            "title": "Completed Task",
            "url": "https://example.com/done",
            "quality": "best",
            "format": "mp4",
            "status": "completed",
            "filename": '<img src=x onerror="window.__xss_filename = true">video.mp4',
            "progress": 100.0,
            "provider": "Direct",
            "provider_id": "direct",
        },
    ]

    # Intercept index page, JS assets, and queue API with proper content-types
    page.route(
        f"{BASE_TEST_URL}/",
        lambda route: route.fulfill(status=200, content_type="text/html", body=html_content),
    )
    page.route(
        f"{BASE_TEST_URL}/static/js/app.js",
        lambda route: route.fulfill(status=200, content_type="application/javascript", body=app_js),
    )
    page.route(
        f"{BASE_TEST_URL}/api/queue",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "tasks": malicious_tasks,
                "providers": [],
                "max_concurrent": 3,
            }),
        ),
    )

    page.goto(f"{BASE_TEST_URL}/")

    # Wait for queue fetching and DOM rendering to finish
    page.wait_for_selector(".task-item", timeout=5000)
    page.wait_for_timeout(500)

    # Assert that no XSS payload executed in window scope
    assert page.evaluate("window.__xss_title") is None, "XSS executed via task.title!"
    assert page.evaluate("window.__xss_url") is None, "XSS executed via task.url!"
    assert page.evaluate("window.__xss_thumb") is None, "XSS executed via task.thumbnail onerror breakout!"
    assert page.evaluate("window.__xss_js_url") is None, "XSS executed via task.thumbnail javascript: scheme!"
    assert page.evaluate("window.__xss_error") is None, "XSS executed via task.error_message!"
    assert page.evaluate("window.__xss_filename") is None, "XSS executed via task.filename!"
    assert page.evaluate("window.__xss_provider") is None, "XSS executed via task.provider!"

    # Verify that the text is rendered as safe text content rather than unescaped HTML tags
    title_text = page.locator(".task-title").first.inner_text()
    assert "<img" in title_text

    error_text = page.locator(".task-error-text").first.inner_text()
    assert "<img" in error_text

    page.close()
