import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from server.app import StreamDLServer, create_app
from server.downloader import DownloadManager
from server.events import QueuePublisher
from server.models import SettingsPatch
from server.task import DownloadTask


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"url": " "},
        {"url": 123},
        {"url": "x", "quality": "4k"},
        {"url": "x", "format": "exe"},
        {"url": "x", "headers": {"Cookie": 123}},
    ],
)
@pytest.mark.parametrize("path", ["/api/download", "/download"])
def test_download_validation(client, body, path):
    response = client.post(path, json=body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_concurrent", 0),
        ("max_concurrent", 11),
        ("max_concurrent_per_provider", 11),
        ("port", 0),
        ("port", 65536),
        ("tls_mode", "off"),
        ("default_quality", "4k"),
        ("default_format", "exe"),
        ("download_dir", ""),
    ],
)
def test_settings_validation(client, field, value):
    assert client.post("/api/settings", json={field: value}).status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_concurrent", 1),
        ("max_concurrent", 10),
        ("port", 1),
        ("port", 65535),
        ("tls_mode", "strict"),
        ("tls_mode", "auto"),
        ("tls_mode", "permissive"),
    ],
)
def test_settings_boundaries(field, value):
    assert SettingsPatch.model_validate({field: value}).model_dump(
        exclude_unset=True
    ) == {field: value}


@pytest.mark.parametrize(
    "patterns", ["*.example.com,*.example.org", ["*.example.com", "*.example.org"]]
)
def test_provider_patterns_and_partial_settings(client, patterns):
    before = client.get("/api/settings").json()["settings"]
    response = client.post(
        "/api/settings", json={"providers": [{"name": "Example", "patterns": patterns}]}
    )
    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["providers"][0]["patterns"] == ["*.example.com", "*.example.org"]
    assert settings["download_dir"] == before["download_dir"]
    assert settings["port"] == before["port"]


@pytest.mark.parametrize("alias", ["tls_verify", "check_certificate"])
def test_legacy_tls_alias(client, alias):
    assert (
        client.post("/api/settings", json={alias: False}).json()["settings"]["tls_mode"]
        == "permissive"
    )


def test_docs_and_headers(client, manager):
    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert client.get(path).status_code == 200
    schema = client.get("/openapi.json").json()
    assert "TaskResponse" in schema["components"]["schemas"]
    assert (
        "text/event-stream"
        in schema["paths"]["/api/events"]["get"]["responses"]["200"]["content"]
    )
    headers = {
        "rEfErEr": " https://example.com/raw ",
        "Cookie": "a=b; c=d",
        "Origin": "https://example.com",
        "User-Agent": " Raw Agent ",
    }
    response = client.post(
        "/download",
        json={
            "url": "https://example.com/raw?signature=a%2Bb",
            "headers": headers,
            "referer": "https://fallback.example.com/",
        },
    )
    assert response.status_code == 200
    task = manager.tasks[response.json()["task"]["id"]]
    assert task.headers == headers


def test_manager_lifecycle_is_explicit_and_idempotent(isolated_env):
    manager = DownloadManager()
    assert manager._dispatcher_thread is None
    manager.start()
    dispatcher = manager._dispatcher_thread
    assert dispatcher is not None
    manager.start()
    assert manager._dispatcher_thread is dispatcher
    task = manager.add_task("https://example.com/lifecycle")
    manager.stop()
    manager.stop()
    assert task.pause_requested
    assert not task.cancel_requested
    assert not dispatcher.is_alive()
    assert not manager.resume_task(task.id)


def test_publisher_latest_only_idle_and_recovery():
    async def scenario():
        state = {"value": 0}
        calls = 0
        fail = False

        def snapshot():
            nonlocal calls
            calls += 1
            if fail:
                raise OSError("temporary read failure")
            return dict(state)

        publisher = QueuePublisher(snapshot, interval=0.01)
        assert publisher.heartbeat == 15
        await asyncio.sleep(0.025)
        assert calls == 0
        first = await publisher.subscribe()
        assert await first.get() == {"value": 0}
        second = await publisher.subscribe()
        assert await second.get() == {"value": 0}
        await asyncio.sleep(0.025)
        assert first.empty() and second.empty()
        fail = True
        await asyncio.sleep(0.025)
        fail = False
        state["value"] = 1
        await asyncio.sleep(0.025)
        state["value"] = 2
        await asyncio.sleep(0.025)
        assert first.qsize() == second.qsize() == 1
        assert await first.get() == await second.get() == {"value": 2}
        await publisher.unsubscribe(first)
        await publisher.unsubscribe(second)
        before = calls
        await asyncio.sleep(0.025)
        assert calls == before
        assert publisher._task is None
        third = await publisher.subscribe()
        assert await third.get() == {"value": 2}
        await publisher.unsubscribe(third)
        await publisher.stop()

    asyncio.run(scenario())


@pytest.fixture
def streaming_server(isolated_env, monkeypatch):
    def local_download(task):
        task.status = "downloading"
        while not task.pause_requested and not task.cancel_requested:
            time.sleep(0.01)

    monkeypatch.setattr("server.downloader.execute_download", local_download)
    app = create_app(isolated_env["manager"])
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = StreamDLServer(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    app.state.publisher.heartbeat = 0.1
    yield f"http://127.0.0.1:{port}", app, server, thread
    server.should_exit = True
    thread.join(6)
    sock.close()
    assert not thread.is_alive()


def next_event(lines):
    event = []
    for line in lines:
        if line:
            event.append(line)
        elif event:
            return event
    raise AssertionError("SSE stream ended")


def test_sse_wire_snapshot_change_heartbeat_reconnect(streaming_server):
    base, app, _, _ = streaming_server
    with httpx.Client(base_url=base, timeout=3) as client:
        expected = client.get("/api/queue").json()
        with client.stream("GET", "/api/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-cache"
            assert response.headers["x-accel-buffering"] == "no"
            lines = response.iter_lines()
            event = next_event(lines)
            assert "event: queue" in event and "retry: 3000" in event
            assert (
                json.loads(
                    next(line[6:] for line in event if line.startswith("data: "))
                )
                == expected
            )
            assert next_event(lines) == [": heartbeat"]
            result = client.post(
                "/api/download", json={"url": "https://example.com/wire"}
            )
            assert result.status_code == 200
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                event = next_event(lines)
                data = next(
                    (line[6:] for line in event if line.startswith("data: ")), None
                )
                if data and json.loads(data)["tasks"]:
                    break
            else:
                pytest.fail("No changed queue event")
        deadline = time.monotonic() + 2
        while app.state.publisher._subscribers and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not app.state.publisher._subscribers
        with client.stream(
            "GET", "/api/events", headers={"Last-Event-ID": "obsolete"}
        ) as response:
            event = next_event(response.iter_lines())
            snapshot = json.loads(
                next(line[6:] for line in event if line.startswith("data: "))
            )
            assert snapshot == client.get("/api/queue").json()
            assert not any(line.startswith("id:") for line in event)


@pytest.mark.parametrize(
    "total_bytes",
    [0, 136592385, 136592385.88235295],
    ids=["unknown", "exact-size", "fractional-estimate"],
)
def test_queue_and_sse_accept_estimated_sizes(streaming_server, manager, total_bytes):
    task = DownloadTask("estimated-size", "https://example.com/estimate")
    task.status = "paused"
    task.pause_requested = True
    task.total_bytes = total_bytes
    with manager._lock:
        manager.tasks[task.id] = task
        manager.task_order.append(task.id)

    base, _, _, _ = streaming_server
    with httpx.Client(base_url=base, timeout=3) as client:
        response = client.get("/api/queue")
        assert response.status_code == 200
        snapshot = response.json()
        assert snapshot["tasks"][0]["total_bytes"] == total_bytes
        with client.stream("GET", "/api/events") as stream:
            event = next_event(stream.iter_lines())
            data = next(line[6:] for line in event if line.startswith("data: "))
            assert json.loads(data) == snapshot


def test_uvicorn_shutdown_with_open_stream(streaming_server, caplog):
    base, _, server, thread = streaming_server
    with httpx.stream("GET", base + "/api/events", timeout=3) as response:
        assert "event: queue" in next_event(response.iter_lines())
        server.should_exit = True
        thread.join(6)
        assert not thread.is_alive()
    assert "timeout graceful shutdown exceeded" not in caplog.text
    assert "Exception in ASGI application" not in caplog.text


def test_shutdown_join_budget_preserves_partials(isolated_env, caplog):
    manager = DownloadManager()
    task = manager.add_task("https://example.com/partial")
    task.status = "downloading"
    partial = isolated_env["download_dir"] / "retained.mp4.part"
    partial.write_bytes(b"partial data")
    release = threading.Event()
    worker = threading.Thread(target=release.wait, daemon=True)
    worker.start()
    manager._active_threads[task.id] = worker
    try:
        started = time.monotonic()
        manager.stop(timeout=0.05)
        assert time.monotonic() - started < 0.5
        assert task.pause_requested and not task.cancel_requested
        assert not task.resume_requested
        assert partial.read_bytes() == b"partial data"
        assert "timed out" in caplog.text
    finally:
        release.set()
        worker.join(1)


@pytest.mark.parametrize(
    "body", [{"download_dir": "   "}, {"providers": [{"name": " "}]}]
)
def test_blank_settings_rejected(client, body):
    assert client.post("/api/settings", json=body).status_code == 422


def test_domain_error_docs_and_request_examples(client):
    schema = client.get("/openapi.json").json()
    assert "409" in schema["paths"]["/api/download"]["post"]["responses"]
    assert "403" in schema["paths"]["/api/open-file/{task_id}"]["post"]["responses"]
    assert schema["components"]["schemas"]["DownloadRequest"]["examples"]
    assert schema["components"]["schemas"]["SettingsPatch"]["examples"]
