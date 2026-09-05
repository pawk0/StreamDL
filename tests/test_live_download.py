import os
import time
import pytest

from server.config import save_settings


@pytest.mark.live
def test_hls_stream_download(manager, tmp_path):
    """
    Live network integration test downloading a real public HLS stream.
    Deselect in fast test runs using: pytest -m "not live"
    """
    test_dir = tmp_path / "live_downloads"
    test_dir.mkdir(parents=True, exist_ok=True)
    save_settings({
        "download_dir": str(test_dir),
        "max_concurrent": 2
    })

    url = "https://test-streams.mux.dev/test_001/stream.m3u8"
    task = manager.add_task(
        url=url,
        title="Mux Test 001 HLS",
        quality="best",
        fmt="mp4"
    )

    # Wait for task to complete (timeout: 90s)
    start_t = time.time()
    completed = False
    while time.time() - start_t < 90:
        time.sleep(1)
        t = manager.get_task(task.id)
        if t["status"] == "completed":
            completed = True
            break
        elif t["status"] == "failed":
            pytest.fail(f"Download failed: {t.get('error_message')}")

    assert completed is True, "Download did not complete within timeout"
    t = manager.get_task(task.id)
    assert t["filepath"] is not None
    assert os.path.exists(t["filepath"])
    assert os.path.getsize(t["filepath"]) > 100000
