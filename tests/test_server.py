import json
import pytest

from server.config import load_settings, save_settings
from server.utils import sanitize_filename, is_generic_title
from server.resolvers import is_doodstream_url


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
    assert task.status in ["queued", "downloading"]

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


def test_index_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"Video Stream Downloader" in res.data or b"settings" in res.data


def test_cancel_nonexistent_task_404(client):
    res = client.post("/api/cancel/nonexistent-task-id-12345")
    assert res.status_code == 404
    data = res.get_json()
    assert data["success"] is False
    assert "error" in data


def test_open_folder_success(client, monkeypatch, tmp_path):
    download_dir = tmp_path / "open_folder_test"
    download_dir.mkdir(parents=True, exist_ok=True)
    save_settings({"download_dir": str(download_dir)})

    opened = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: opened.append(args[1]))

    res = client.post("/api/open-folder")
    assert res.status_code == 200
    assert res.get_json()["success"] is True
    assert len(opened) == 1


def test_open_folder_not_found(client, monkeypatch):
    monkeypatch.setattr("os.path.exists", lambda p: False)
    res_missing = client.post("/api/open-folder")
    assert res_missing.status_code == 404
    assert res_missing.get_json()["success"] is False


def test_open_folder_error(client, monkeypatch, tmp_path):
    download_dir = tmp_path / "open_folder_err"
    download_dir.mkdir(parents=True, exist_ok=True)
    save_settings({"download_dir": str(download_dir)})

    def raise_err(p):
        raise OSError("Permission denied")
    monkeypatch.setattr("os.startfile", raise_err, raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("Permission denied")))

    res_err = client.post("/api/open-folder")
    assert res_err.status_code == 500
    assert res_err.get_json()["success"] is False


def test_open_file_endpoints(client, manager, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: opened.append(args[1]))

    # 1. Nonexistent task ID -> 404
    res = client.post("/api/open-file/ghost_task_9999")
    assert res.status_code == 404
    assert "Filepath not recorded" in res.get_json()["error"]

    # 2. Task with no filepath recorded -> 404
    task_nofile = manager.add_task(url="https://example.com/no_file")
    res_nofile = client.post(f"/api/open-file/{task_nofile.id}")
    assert res_nofile.status_code == 404
    assert "Filepath not recorded" in res_nofile.get_json()["error"]

    # 3. File recorded but missing on disk -> 404
    task_missing = manager.add_task(url="https://example.com/missing")
    task_missing.filepath = str(tmp_path / "missing_video.mp4")
    res_missing = client.post(f"/api/open-file/{task_missing.id}")
    assert res_missing.status_code == 404
    assert "File does not exist" in res_missing.get_json()["error"]

    # 4. File recorded and exists on disk -> 200
    real_file = tmp_path / "real_video.mp4"
    real_file.write_text("dummy video content")
    task_ok = manager.add_task(url="https://example.com/ok")
    task_ok.filepath = str(real_file)
    res_ok = client.post(f"/api/open-file/{task_ok.id}")
    assert res_ok.status_code == 200
    assert res_ok.get_json()["success"] is True
    assert len(opened) == 1

    # 5. Exception during opening -> 500
    def raise_err(p):
        raise OSError("Cannot open file")
    monkeypatch.setattr("os.startfile", raise_err, raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("Cannot open file")))

    res_err = client.post(f"/api/open-file/{task_ok.id}")
    assert res_err.status_code == 500
    assert res_err.get_json()["success"] is False

