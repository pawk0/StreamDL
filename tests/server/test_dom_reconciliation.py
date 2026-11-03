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
    page.route("https://**/*", lambda route: route.abort())
    page.add_init_script("""
        window.__eventSources = [];
        window.EventSource = class {
            constructor(url) { this.url = url; this.closed = false; window.__eventSources.push(this); }
            addEventListener(name, callback) {
                if (name === 'queue') fetch('/api/queue').then(r => r.json()).then(data => callback({ data: JSON.stringify({ providers: [], ...data }) }));
            }
            close() { this.closed = true; }
        };
    """)

    html_content = INDEX_HTML_PATH.read_text(encoding="utf-8")

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
        f"{BASE_TEST_URL}/static/js/*.js",
        lambda route: route.fulfill(status=200, content_type="application/javascript", body=(APP_JS_PATH.parent / route.request.url.rsplit("/", 1)[-1]).read_text(encoding="utf-8")),
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
    page.route("https://**/*", lambda route: route.abort())
    page.add_init_script("""
        window.__eventSources = [];
        window.EventSource = class {
            constructor(url) { this.url = url; this.closed = false; window.__eventSources.push(this); }
            addEventListener(name, callback) {
                if (name === 'queue') fetch('/api/queue').then(r => r.json()).then(data => callback({ data: JSON.stringify({ providers: [], ...data }) }));
            }
            close() { this.closed = true; }
        };
    """)

    html_content = INDEX_HTML_PATH.read_text(encoding="utf-8")

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
        f"{BASE_TEST_URL}/static/js/*.js",
        lambda route: route.fulfill(status=200, content_type="application/javascript", body=(APP_JS_PATH.parent / route.request.url.rsplit("/", 1)[-1]).read_text(encoding="utf-8")),
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


@pytest.mark.parametrize('selector', ['.task-title', '.task-url', '.task-metrics', '.task-error-text'])
def test_selection_survives_queue_refresh(browser_context, selector):
    page = browser_context.new_page()
    page.route("https://**/*", lambda route: route.abort())
    page.add_init_script("""
        window.__eventSources = [];
        window.EventSource = class {
            constructor(url) { this.url = url; this.closed = false; window.__eventSources.push(this); }
            addEventListener(name, callback) {
                if (name === 'queue') fetch('/api/queue').then(r => r.json()).then(data => callback({ data: JSON.stringify({ providers: [], ...data }) }));
            }
            close() { this.closed = true; }
        };
    """)
    task = {
        'id': 'selected-task',
        'title': 'A title to copy',
        'url': 'https://example.com/video.mp4',
        'status': 'failed' if selector == '.task-error-text' else 'downloading',
        'error_message': 'An error to copy',
        'progress': 10,
        'downloaded_str': '10MB',
    }
    other_task = {**task, 'id': 'other-task', 'status': 'downloading'}
    page.route('**/*', lambda route: route.abort())
    page.route(
        f'{BASE_TEST_URL}/',
        lambda route: route.fulfill(content_type='text/html', body=INDEX_HTML_PATH.read_text(encoding='utf-8')),
    )
    page.route(
        f'{BASE_TEST_URL}/static/js/*.js',
        lambda route: route.fulfill(content_type='application/javascript', body=(APP_JS_PATH.parent / route.request.url.rsplit("/", 1)[-1]).read_text(encoding="utf-8")),
    )
    page.route(
        f'{BASE_TEST_URL}/api/queue',
        lambda route: route.fulfill(json={'tasks': [task, other_task]}),
    )
    # Control refreshes explicitly to avoid timing-dependent assertions.
    page.add_init_script('window.setInterval = () => 0;')
    try:
        page.goto(f'{BASE_TEST_URL}/')
        page.wait_for_selector('.task-item')
        selected_text = page.evaluate('''selector => {
            const node = document.querySelector('.task-item ' + selector);
            const range = document.createRange();
            range.selectNodeContents(node);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return selection.toString();
        }''', selector)
        assert selected_text

        # An unchanged poll must not move cards and destroy the selection.
        page.evaluate('window.__testFetchQueue()')
        assert page.evaluate('window.getSelection().toString()') == selected_text

        task['progress'] = 85
        task['downloaded_str'] = '85MB'
        other_task['progress'] = 60
        page.evaluate('window.__testFetchQueue()')
        assert page.evaluate('window.getSelection().toString()') == selected_text
        assert '60%' in page.locator('[data-id="other-task"] .progress-bar-fill').get_attribute('style')

        # The selected card catches up on the first refresh after deselection.
        page.evaluate('window.getSelection().removeAllRanges()')
        page.evaluate('window.__testFetchQueue()')
        assert '85%' in page.locator('[data-id="selected-task"] .progress-bar-fill').get_attribute('style')
    finally:
        page.close()


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_clear_individual_task(browser_context, status):
    from playwright.sync_api import expect

    page = browser_context.new_page()
    page.route("https://**/*", lambda route: route.abort())
    page.add_init_script("""
        window.__eventSources = [];
        window.EventSource = class {
            constructor(url) { this.url = url; this.closed = false; window.__eventSources.push(this); }
            addEventListener(name, callback) {
                if (name === 'queue') fetch('/api/queue').then(r => r.json()).then(data => callback({ data: JSON.stringify({ providers: [], ...data }) }));
            }
            close() { this.closed = true; }
        };
    """)
    tasks = [
        {"id": "target", "title": "Finished", "status": status, "progress": 100},
        {"id": "other", "title": "Running", "status": "downloading", "progress": 25},
    ]
    requests = []
    page.route("**/*", lambda route: route.abort())
    page.route(f"{BASE_TEST_URL}/", lambda route: route.fulfill(
        content_type="text/html", body=INDEX_HTML_PATH.read_text(encoding="utf-8")))
    page.route(f"{BASE_TEST_URL}/static/js/*.js", lambda route: route.fulfill(
        content_type="application/javascript", body=(APP_JS_PATH.parent / route.request.url.rsplit("/", 1)[-1]).read_text(encoding="utf-8")))
    page.route(f"{BASE_TEST_URL}/api/queue", lambda route: route.fulfill(json={"tasks": tasks}))

    def clear(route):
        requests.append((route.request.url, route.request.method))
        tasks.pop(0)
        route.fulfill(json={"success": True})

    page.route(f"{BASE_TEST_URL}/api/clear/target", clear)
    try:
        page.goto(f"{BASE_TEST_URL}/")
        expect(page.locator('[data-id="other"] .btn-clear-task')).to_have_count(0)
        page.get_by_role("button", name="Clear task", exact=True).click()
        expect(page.locator('.task-item[data-id="target"]')).to_have_count(0)
        expect(page.locator('.task-item[data-id="other"]')).to_be_visible()
        assert requests == [(f"{BASE_TEST_URL}/api/clear/target", "POST")]
    finally:
        page.close()


def test_pause_resume_dashboard_controls(browser_context):
    from playwright.sync_api import expect

    page = browser_context.new_page()
    page.route("https://**/*", lambda route: route.abort())
    page.add_init_script("""
        window.__eventSources = [];
        window.EventSource = class {
            constructor(url) { this.url = url; this.closed = false; window.__eventSources.push(this); }
            addEventListener(name, callback) {
                if (name === 'queue') fetch('/api/queue').then(r => r.json()).then(data => callback({ data: JSON.stringify({ providers: [], ...data }) }));
            }
            close() { this.closed = true; }
        };
    """)
    task = {
        "id": "pause-test", "title": "Pause Test", "url": "https://example.com/video.mp4",
        "quality": "best", "format": "mp4", "status": "downloading", "progress": 25,
        "downloaded_str": "25MB", "total_str": "100MB", "speed": "1MB/s", "eta": "75s",
    }
    actions = []
    page.route("**/*", lambda route: route.abort())
    page.route(f"{BASE_TEST_URL}/", lambda route: route.fulfill(
        content_type="text/html", body=INDEX_HTML_PATH.read_text(encoding="utf-8")))
    page.route(f"{BASE_TEST_URL}/static/js/*.js", lambda route: route.fulfill(
        content_type="application/javascript", body=(APP_JS_PATH.parent / route.request.url.rsplit("/", 1)[-1]).read_text(encoding="utf-8")))
    page.route(f"{BASE_TEST_URL}/api/queue", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"tasks": [task], "providers": [], "max_concurrent": 1})))

    def control(route):
        action = route.request.url.split("/")[-2]
        actions.append((action, route.request.method))
        task["status"] = "paused" if action == "pause" else "downloading"
        route.fulfill(content_type="application/json", body=json.dumps({"success": True}))

    page.route(f"{BASE_TEST_URL}/api/pause/*", control)
    page.route(f"{BASE_TEST_URL}/api/resume/*", control)
    try:
        page.goto(f"{BASE_TEST_URL}/")
        page.get_by_role("button", name="Pause download", exact=True).click()
        expect(page.locator(".badge-paused")).to_have_text("Paused")
        expect(page.get_by_role("button", name="Cancel download", exact=True)).to_be_visible()
        page.locator('[data-filter="active"]').click()
        expect(page.get_by_role("button", name="Resume download", exact=True)).to_be_visible()
        page.get_by_role("button", name="Resume download", exact=True).click()
        expect(page.locator(".badge-downloading")).to_have_text("Downloading")
        expect(page.get_by_role("button", name="Pause download", exact=True)).to_be_visible()
        assert actions == [("pause", "POST"), ("resume", "POST")]
    finally:
        page.close()


@pytest.mark.parametrize("interaction", ["pointer", "keyboard", "pending-request"])
def test_pause_control_survives_progress_refresh(browser_context, interaction):
    from playwright.sync_api import expect

    page = browser_context.new_page()
    page.route("https://**/*", lambda route: route.abort())
    page.add_init_script("""
        window.__eventSources = [];
        window.EventSource = class {
            constructor(url) { this.url = url; this.closed = false; window.__eventSources.push(this); }
            addEventListener(name, callback) {
                if (name === 'queue') fetch('/api/queue').then(r => r.json()).then(data => callback({ data: JSON.stringify({ providers: [], ...data }) }));
            }
            close() { this.closed = true; }
        };
    """)
    task = {
        "id": "stable-button", "title": "Running download", "url": "https://example.com/video.mp4",
        "status": "downloading", "progress": 10, "downloaded_str": "10MB", "total_str": "100MB",
    }
    requests = []
    page.route("**/*", lambda route: route.abort())
    page.route(f"{BASE_TEST_URL}/", lambda route: route.fulfill(
        content_type="text/html", body=INDEX_HTML_PATH.read_text(encoding="utf-8")))
    page.route(f"{BASE_TEST_URL}/static/js/*.js", lambda route: route.fulfill(
        content_type="application/javascript", body=(APP_JS_PATH.parent / route.request.url.rsplit("/", 1)[-1]).read_text(encoding="utf-8")))
    page.route(f"{BASE_TEST_URL}/api/queue", lambda route: route.fulfill(json={"tasks": [task]}))
    page.route(f"{BASE_TEST_URL}/api/pause/*", lambda route: requests.append(route))
    page.add_init_script("window.setInterval = () => 0;")
    try:
        page.goto(f"{BASE_TEST_URL}/")
        button = page.get_by_role("button", name="Pause download", exact=True)
        expect(button).to_be_visible()
        page.evaluate("window.originalPause = document.querySelector('.btn-pause')")
        if interaction == "pointer":
            button.hover()
            page.mouse.down()
        elif interaction == "keyboard":
            button.focus()
        else:
            button.click()
            expect(button).to_be_disabled()

        for progress in (25, 50, 75):
            task["progress"] = progress
            task["downloaded_str"] = f"{progress}MB"
            page.evaluate("window.__testFetchQueue()")
            expect(page.locator(".progress-bar-fill")).to_have_attribute("style", f"width: {progress}%;")
            assert page.evaluate("window.originalPause === document.querySelector('.btn-pause')")
            if interaction == "pointer":
                assert button.evaluate("node => node.matches(':hover')")
            elif interaction == "keyboard":
                expect(button).to_be_focused()
            else:
                expect(button).to_be_disabled()

        if interaction == "pointer":
            page.mouse.up()
        elif interaction == "keyboard":
            page.keyboard.press("Enter")
        expect(button).to_be_disabled()
        assert len(requests) == 1
        requests[0].fulfill(json={"success": True})
        expect(button).to_be_enabled()
    finally:
        page.close()


def test_dashboard_settings_mapping_and_download_workflow(browser_context):
    """Exercise the module boundaries with the real module loader and mocked API."""
    from playwright.sync_api import expect

    page = browser_context.new_page()
    page.route("https://**/*", lambda route: route.abort())
    page.add_init_script("""
        window.__eventSources = [];
        window.EventSource = class {
            constructor(url) { this.url = url; this.closed = false; window.__eventSources.push(this); }
            addEventListener(name, callback) {
                if (name === 'queue') fetch('/api/queue').then(r => r.json()).then(data => callback({ data: JSON.stringify({ providers: [], ...data }) }));
            }
            close() { this.closed = true; }
        };
    """)
    settings = {"providers": [], "max_concurrent": 3, "download_dir": "test-downloads"}
    downloads = []
    task = {
        "id": "mapping-task", "title": "Sample", "url": "https://example.com/video.mp4",
        "status": "queued", "provider_id": "example.com", "provider": "example.com",
    }

    def settings_response(route):
        if route.request.method == "POST":
            settings.update(route.request.post_data_json)
        route.fulfill(json={"success": True, "settings": settings})

    def download_response(route):
        downloads.append(route.request.post_data_json)
        route.fulfill(json={"success": True})

    page.route("**/*", lambda route: route.abort())
    page.route(f"{BASE_TEST_URL}/", lambda route: route.fulfill(
        content_type="text/html", body=INDEX_HTML_PATH.read_text(encoding="utf-8")))
    page.route(f"{BASE_TEST_URL}/static/js/*.js", lambda route: route.fulfill(
        content_type="application/javascript",
        body=(APP_JS_PATH.parent / route.request.url.rsplit("/", 1)[-1]).read_text(encoding="utf-8")))
    page.route(f"{BASE_TEST_URL}/api/queue", lambda route: route.fulfill(json={
        "tasks": [task], "providers": settings["providers"], "max_concurrent": settings["max_concurrent"],
    }))
    page.route(f"{BASE_TEST_URL}/api/settings", settings_response)
    page.route(f"{BASE_TEST_URL}/api/download", download_response)
    page.add_init_script("window.setInterval = () => 0;")
    try:
        page.goto(f"{BASE_TEST_URL}/")
        page.locator(".btn-map-provider").click()
        expect(page.locator("#modal-map-provider")).to_have_class("modal-backdrop open")
        page.locator("#input-new-provider-name").fill("Example")
        page.locator("#btn-submit-new-provider").click()
        expect(page.locator("#modal-map-provider")).not_to_have_class("modal-backdrop open")
        assert settings["providers"][0]["patterns"] == ["*example.com*"]

        # A fresh queue response supplies providers to the mapping controller.
        page.locator(".btn-map-provider").click()
        expect(page.locator("#select-existing-provider option")).to_have_text("Example (limit: 1)")
        page.keyboard.press("Escape")
        expect(page.locator("#modal-map-provider")).not_to_have_class("modal-backdrop open")

        page.locator("#btn-open-settings").click()
        expect(page.locator(".provider-name-input")).to_have_value("Example")
        page.locator("#setting-folder").fill("updated-downloads")
        page.locator('#form-settings button[type="submit"]').click()
        expect(page.locator("#modal-settings")).not_to_have_class("modal-backdrop open")
        assert settings["download_dir"] == "updated-downloads"

        page.locator('.tab-btn[data-filter="completed"]').click()
        expect(page.locator(".task-item")).to_have_count(0)
        page.locator('.tab-btn[data-filter="all"]').click()
        expect(page.locator(".task-item")).to_have_count(1)
        page.locator("#input-url").fill("https://example.com/new.mp4")
        page.locator('#form-download button[type="submit"]').click()
        expect(page.locator("#input-url")).to_have_value("")
        assert downloads == [{"url": "https://example.com/new.mp4", "quality": "best", "format": "mp4"}]
    finally:
        page.close()


def test_sse_status_reconnect_lifecycle_and_stale_refresh(browser_context):
    page = browser_context.new_page()
    page.route('**/*', lambda route: route.abort())
    page.route(f'{BASE_TEST_URL}/', lambda route: route.fulfill(content_type='text/html', body=INDEX_HTML_PATH.read_text(encoding='utf-8')))
    page.route(f'{BASE_TEST_URL}/static/js/*.js', lambda route: route.fulfill(content_type='application/javascript', body=(APP_JS_PATH.parent / route.request.url.rsplit('/', 1)[-1]).read_text(encoding='utf-8')))
    page.add_init_script("""
        window.__sources = [];
        window.EventSource = class {
            constructor(url) { this.handlers = {}; this.closed = false; window.__sources.push(this); }
            addEventListener(name, callback) { this.handlers[name] = callback; }
            close() { this.closed = true; }
        };
        window.__emit = data => window.__sources.at(-1).handlers.queue({data: JSON.stringify(data)});
        window.__refreshes = 0;
        window.fetch = () => {
            window.__refreshes++;
            return new Promise(resolve => window.__resolveRefresh = data => resolve({ok:true, json:async () => data}));
        };
    """)
    try:
        page.goto(BASE_TEST_URL)
        page.wait_for_function('window.__sources.length === 1')
        assert page.locator('#server-status-text').inner_text() == 'Connecting'
        assert page.evaluate('window.__refreshes') == 0
        page.evaluate("window.__emit({tasks:[], providers:[]})")
        assert page.locator('#server-status-text').inner_text() == 'Connected'
        page.evaluate("window.__sources[0].onerror()")
        assert page.locator('#server-status-text').inner_text() == 'Reconnecting'
        page.evaluate("window.__testFetchQueue(); window.__emit({tasks:[{id:'fresh',title:'Fresh SSE',status:'queued'}],providers:[]}); window.__resolveRefresh({tasks:[],providers:[]})")
        page.wait_for_selector('.task-item[data-id="fresh"]')
        assert page.locator('#server-status-text').inner_text() == 'Connected'
        assert page.locator('.task-item').count() == 1
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
        assert page.evaluate('window.__sources[0].closed')
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow'))")
        assert page.evaluate('window.__sources.length') == 2
        assert page.locator('#server-status-text').inner_text() == 'Reconnecting'
        page.evaluate("window.__sources[1].handlers.queue({data:'invalid'})")
        assert page.locator('#server-status-text').inner_text() == 'Reconnecting'
        assert page.locator('.task-item').count() == 1
        page.evaluate("window.__emit({tasks:[],providers:[]})")
        assert page.locator('#server-status-text').inner_text() == 'Connected'
    finally:
        page.close()


@pytest.mark.parametrize("body,expected", [
    (None, "Fallback"),
    ({"error": "Domain error"}, "Domain error"),
    ({"detail": "Request error"}, "Request error"),
    ({"detail": [{"loc": ["body", "providers", 0, "name"], "msg": "Required", "input": "secret", "ctx": {"secret": "hidden"}}]}, "providers.0.name: Required"),
])
def test_dashboard_validation_errors_exclude_inputs(browser_context, body, expected):
    page = browser_context.new_page()
    page.route('**/*', lambda route: route.abort())
    page.route(f'{BASE_TEST_URL}/', lambda route: route.fulfill(content_type='text/html', body='<html></html>'))
    page.route(f'{BASE_TEST_URL}/static/js/ui.js', lambda route: route.fulfill(content_type='application/javascript', body=(APP_JS_PATH.parent / 'ui.js').read_text(encoding='utf-8')))
    try:
        page.goto(BASE_TEST_URL)
        result = page.evaluate("""async body => {
            const {apiError} = await import('/static/js/ui.js');
            return apiError(body, 'Fallback');
        }""", body)
        assert result == expected
        assert 'secret' not in result
    finally:
        page.close()
