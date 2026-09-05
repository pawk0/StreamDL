import json
import pytest

from server.config import load_settings, save_settings
from server.downloader import sanitize_filename, is_generic_title, is_doodstream_url


def test_status_endpoint(client):
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "online"
    assert "max_concurrent" in data
    assert "download_dir" in data
    assert data["active_count"] == 0


def test_settings_get_and_post(client):
    # Update settings
    new_settings = {
        "max_concurrent": 4,
        "default_quality": "720p",
        "default_format": "mkv"
    }
    res = client.post(
        "/api/settings",
        data=json.dumps(new_settings),
        content_type="application/json"
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["settings"]["max_concurrent"] == 4
    assert data["settings"]["default_quality"] == "720p"

    # Verify GET settings returns updated values
    res_get = client.get("/api/settings")
    assert res_get.status_code == 200
    assert res_get.get_json()["settings"]["max_concurrent"] == 4


def test_download_endpoint_validation(client):
    # Missing url
    res = client.post(
        "/api/download",
        data=json.dumps({}),
        content_type="application/json"
    )
    assert res.status_code == 400

    # Valid url queuing
    res = client.post(
        "/api/download",
        data=json.dumps({
            "url": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
            "title": "Big Buck Bunny HLS",
            "quality": "720p",
            "format": "mp4"
        }),
        content_type="application/json"
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["task"]["title"] == "Big Buck Bunny HLS"
    task_id = data["task"]["id"]

    # Check queue
    res_queue = client.get("/api/queue")
    assert res_queue.status_code == 200
    q_data = res_queue.get_json()
    assert len(q_data["tasks"]) == 1
    assert q_data["tasks"][0]["id"] == task_id


def test_cancellation(client, manager):
    task = manager.add_task(
        url="https://example.com/fake.m3u8",
        title="Fake Task"
    )
    assert task.status == "queued"

    res = client.post(f"/api/cancel/{task.id}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True

    updated = manager.get_task(task.id)
    assert updated["status"] == "cancelled"


def test_clear_finished(client, manager):
    task = manager.add_task(url="https://example.com/fake.m3u8")
    manager.cancel_task(task.id)

    res = client.post("/api/clear")
    assert res.status_code == 200
    assert len(manager.get_all_tasks()) == 0


def test_title_sanitization_and_generic_check():
    dirty_title = 'My Video: "Episode 1" <HD> / 2026? *special* | [m3u8]'
    clean = sanitize_filename(dirty_title)
    for char in '<>:"/\\|?*':
        assert char not in clean
    assert clean == "My Video Episode 1 HD 2026 special [m3u8]"

    assert is_generic_title("master") is True
    assert is_generic_title("index") is True
    assert is_generic_title("index-f2-v1-a1") is True
    assert is_generic_title("manifest") is True
    assert is_generic_title("Eliota Intelligence Analysis") is False


@pytest.mark.parametrize("url,expected", [
    ("https://dood.re/e/xyz123", True),
    ("https://doodstream.com/d/abc456", True),
    ("https://dood.to/e/789", True),
    ("https://youtube.com/watch?v=123", False),
])
def test_doodstream_url_detection(url, expected):
    assert is_doodstream_url(url) == expected


def test_queue_endpoint_returns_providers_and_rematches(client, manager):
    task = manager.add_task(url="https://edge1.r66nv9ed.com/video.m3u8")
    assert task.provider_id == "r66nv9ed.com"

    res = client.get("/api/queue")
    assert res.status_code == 200
    data = res.get_json()
    assert "providers" in data
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["provider_id"] == "r66nv9ed.com"

    current_settings = load_settings()
    if "providers" not in current_settings:
        current_settings["providers"] = []
    current_settings["providers"].append({
        "id": "elliotintel",
        "name": "ElliotIntel",
        "patterns": ["*r66nv9ed.com*"],
        "max_concurrent": 2
    })
    res_post = client.post(
        "/api/settings",
        data=json.dumps(current_settings),
        content_type="application/json"
    )
    assert res_post.status_code == 200

    updated = manager.get_task(task.id)
    assert updated["provider_id"] == "elliotintel"
    assert updated["provider"] == "ElliotIntel"
    assert updated["provider_limit"] == 2
