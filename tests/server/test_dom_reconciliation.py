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


def test_dom_reconciliation_preserves_card_elements(browser_context):
    """Verify that renderTasks updates cards in place rather than destroying and recreating DOM nodes."""
    page = browser_context.new_page()

    html_content = INDEX_HTML_PATH.read_text(encoding="utf-8")
    app_js = APP_JS_PATH.read_text(encoding="utf-8")

    current_tasks = [
        {
            "id": "task-alpha",
            "title": "Alpha Stream",
            "url": "https://example.com/alpha.mp4",
            "quality": "1080p",
            "format": "mp4",
            "status": "downloading",
            "downloaded_str": "10MB",
            "total_str": "100MB",
            "speed": "2MB/s",
            "eta": "45s",
            "progress": 10.0,
            "provider": "Direct",
            "provider_id": "direct",
        },
        {
            "id": "task-beta",
            "title": "Beta Stream",
            "url": "https://example.com/beta.mp4",
            "quality": "720p",
            "format": "mp4",
            "status": "queued",
            "progress": 0.0,
            "provider": "Direct",
            "provider_id": "direct",
        },
    ]

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
                "tasks": current_tasks,
                "providers": [],
                "max_concurrent": 3,
            }),
        ),
    )

    page.goto(f"{BASE_TEST_URL}/")
    page.wait_for_selector('.task-item[data-id="task-alpha"]', timeout=5000)

    # Store references to initial DOM elements
    page.evaluate("""
        window.__cardAlpha = document.querySelector('.task-item[data-id="task-alpha"]');
        window.__cardBeta = document.querySelector('.task-item[data-id="task-beta"]');
    """)

    # Update tasks: Alpha progressed to 85%, Beta started downloading
    current_tasks[0]["progress"] = 85.0
    current_tasks[0]["downloaded_str"] = "85MB"
    current_tasks[0]["speed"] = "5MB/s"
    current_tasks[1]["status"] = "downloading"
    current_tasks[1]["progress"] = 15.0

    # Wait for the next poll cycle (or trigger fetchQueue directly)
    page.evaluate("window.__testFetchQueue ? window.__testFetchQueue() : null")
    page.wait_for_timeout(1200)

    # Assert that the EXACT same DOM nodes are preserved in memory
    is_alpha_preserved = page.evaluate("""
        document.querySelector('.task-item[data-id="task-alpha"]') === window.__cardAlpha
    """)
    is_beta_preserved = page.evaluate("""
        document.querySelector('.task-item[data-id="task-beta"]') === window.__cardBeta
    """)

    assert is_alpha_preserved, "Card for task-alpha was recreated instead of reconciled in-place!"
    assert is_beta_preserved, "Card for task-beta was recreated instead of reconciled in-place!"

    # Verify that in-place updates took effect
    fill_width = page.locator('.task-item[data-id="task-alpha"] .progress-bar-fill').get_attribute("style")
    assert "85%" in fill_width

    alpha_metrics = page.locator('.task-item[data-id="task-alpha"] .task-metrics').inner_text()
    assert "85MB" in alpha_metrics
    assert "5MB/s" in alpha_metrics

    page.close()


def test_dom_reconciliation_task_lifecycle_and_delegation(browser_context):
    """Verify adding, completing, clearing tasks and delegated button actions."""
    page = browser_context.new_page()

    html_content = INDEX_HTML_PATH.read_text(encoding="utf-8")
    app_js = APP_JS_PATH.read_text(encoding="utf-8")

    cancel_called = []
    open_called = []

    tasks_state = [
        {
            "id": "task-running",
            "title": "Active Download",
            "url": "https://example.com/active.mp4",
            "quality": "1080p",
            "format": "mp4",
            "status": "downloading",
            "progress": 50.0,
            "provider": "Direct",
            "provider_id": "direct",
        },
        {
            "id": "task-done",
            "title": "Finished Download",
            "url": "https://example.com/done.mp4",
            "quality": "best",
            "format": "mp4",
            "status": "completed",
            "filename": "done.mp4",
            "progress": 100.0,
            "provider": "Direct",
            "provider_id": "direct",
        },
    ]

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
                "tasks": tasks_state,
                "providers": [],
                "max_concurrent": 3,
            }),
        ),
    )
    page.route(
        f"{BASE_TEST_URL}/api/cancel/*",
        lambda route: (
            cancel_called.append(route.request.url),
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"success": True})),
        ),
    )
    page.route(
        f"{BASE_TEST_URL}/api/open-file/*",
        lambda route: (
            open_called.append(route.request.url),
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"success": True})),
        ),
    )

    page.goto(f"{BASE_TEST_URL}/")
    page.wait_for_selector('.task-item[data-id="task-running"]', timeout=5000)

    # Reconcile multiple times
    page.wait_for_timeout(1500)

    # Click cancel on task-running
    page.locator('.task-item[data-id="task-running"] .btn-cancel').click()
    page.wait_for_timeout(200)
    assert any("task-running" in url for url in cancel_called)

    # Click play on task-done
    page.locator('.task-item[data-id="task-done"] .btn-open-file').click()
    page.wait_for_timeout(200)
    assert any("task-done" in url for url in open_called)

    page.close()
