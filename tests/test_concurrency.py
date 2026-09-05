import time
import pytest

from server.task import DownloadTask
from server.config import save_settings


def test_queue_and_concurrency_limit(manager, monkeypatch):
    save_settings({"max_concurrent": 2, "max_concurrent_per_provider": 2})

    executed_tasks = []

    def mock_execute(task: DownloadTask):
        executed_tasks.append(task.id)
        task.status = "downloading"
        while not task.cancel_requested:
            time.sleep(0.05)
        task.status = "cancelled"

    monkeypatch.setattr(manager, "_execute_download", mock_execute)

    # Add 4 tasks
    t1 = manager.add_task("https://example.com/1")
    t2 = manager.add_task("https://example.com/2")
    t3 = manager.add_task("https://example.com/3")
    t4 = manager.add_task("https://example.com/4")

    # Wait for dispatcher loop
    time.sleep(0.9)

    assert len(executed_tasks) == 2
    assert t1.id in executed_tasks
    assert t2.id in executed_tasks
    assert manager.get_task(t3.id)["status"] == "queued"
    assert manager.get_task(t4.id)["status"] == "queued"

    # Cancel task 1 -> slot frees up
    manager.cancel_task(t1.id)
    time.sleep(0.9)

    assert len(executed_tasks) == 3
    assert t3.id in executed_tasks
    assert manager.get_task(t4.id)["status"] == "queued"

    # Increase concurrency from 2 to 4
    save_settings({"max_concurrent": 4, "max_concurrent_per_provider": 4})
    time.sleep(0.9)

    assert len(executed_tasks) == 4
    assert t4.id in executed_tasks

    for t in [t1, t2, t3, t4]:
        manager.cancel_task(t.id)


def test_per_provider_concurrency_independent(manager, monkeypatch):
    save_settings({
        "max_concurrent": 4,
        "max_concurrent_per_provider": 1,
        "providers": [
            {
                "id": "doodstream",
                "name": "Doodstream",
                "patterns": ["*dood*", "*cloudatacdn.com*"],
                "max_concurrent": 1
            },
            {
                "id": "elliotintel",
                "name": "ElliotIntel",
                "patterns": ["*elliot*", "*sprintcdn*", "*r66nv9ed.com*"],
                "max_concurrent": 1
            }
        ]
    })

    executed_tasks = []

    def mock_execute(task: DownloadTask):
        executed_tasks.append(task.id)
        task.status = "downloading"
        while not task.cancel_requested:
            time.sleep(0.05)
        task.status = "cancelled"

    monkeypatch.setattr(manager, "_execute_download", mock_execute)

    t1 = manager.add_task("https://dw572mm.cloudatacdn.com/video1.mp4")
    t2 = manager.add_task("https://r1148gsx.cloudatacdn.com/video2.mp4")
    t3 = manager.add_task("https://edge2-waw-sprintcdn.r66nv9ed.com/stream.m3u8")
    t4 = manager.add_task("https://anotheroption.tv/video4.m3u8")

    assert t1.provider_name == "Doodstream"
    assert t2.provider_name == "Doodstream"
    assert t3.provider_name == "ElliotIntel"
    assert "anotheroption" in t4.provider_name.lower()

    time.sleep(0.9)

    assert len(executed_tasks) == 3
    assert t1.id in executed_tasks
    assert t3.id in executed_tasks
    assert t4.id in executed_tasks

    # t2 throttled because Doodstream limit is 1
    assert t2.id not in executed_tasks
    assert manager.get_task(t2.id)["status"] == "queued"

    # Cancel t1
    manager.cancel_task(t1.id)
    time.sleep(0.9)

    assert t2.id in executed_tasks
    assert len(executed_tasks) == 4

    for t in [t1, t2, t3, t4]:
        manager.cancel_task(t.id)


def test_decrease_global_concurrency_below_active_downloads(manager, monkeypatch):
    save_settings({"max_concurrent": 3, "max_concurrent_per_provider": 3})

    executed_tasks = []
    completed_tasks = set()

    def mock_execute(task: DownloadTask):
        executed_tasks.append(task.id)
        task.status = "downloading"
        while not task.cancel_requested and task.id not in completed_tasks:
            time.sleep(0.05)
        if task.id in completed_tasks:
            task.status = "completed"
        else:
            task.status = "cancelled"

    monkeypatch.setattr(manager, "_execute_download", mock_execute)

    t1 = manager.add_task("https://example.com/1")
    t2 = manager.add_task("https://example.com/2")
    t3 = manager.add_task("https://example.com/3")
    t4 = manager.add_task("https://example.com/4")

    time.sleep(0.9)

    assert len(executed_tasks) == 3
    assert t1.id in executed_tasks
    assert t2.id in executed_tasks
    assert t3.id in executed_tasks
    assert manager.get_task(t4.id)["status"] == "queued"

    # Dynamically decrease max_concurrent from 3 down to 1
    save_settings({"max_concurrent": 1, "max_concurrent_per_provider": 3})
    time.sleep(0.9)

    # Active downloads must NOT be cancelled or interrupted
    assert manager.get_task(t1.id)["status"] == "downloading"
    assert manager.get_task(t2.id)["status"] == "downloading"
    assert manager.get_task(t3.id)["status"] == "downloading"

    # t4 must STILL be queued
    assert len(executed_tasks) == 3
    assert manager.get_task(t4.id)["status"] == "queued"

    # Complete task 1: active drops to 2 (still > 1)
    completed_tasks.add(t1.id)
    time.sleep(0.9)
    assert manager.get_task(t1.id)["status"] == "completed"
    assert len(executed_tasks) == 3
    assert manager.get_task(t4.id)["status"] == "queued"

    # Complete task 2: active drops to 1 (still >= 1)
    completed_tasks.add(t2.id)
    time.sleep(0.9)
    assert manager.get_task(t2.id)["status"] == "completed"
    assert len(executed_tasks) == 3
    assert manager.get_task(t4.id)["status"] == "queued"

    # Complete task 3: active drops to 0 (< 1)
    completed_tasks.add(t3.id)
    time.sleep(0.9)
    assert manager.get_task(t3.id)["status"] == "completed"

    # Now task 4 starts!
    assert len(executed_tasks) == 4
    assert t4.id in executed_tasks
    assert manager.get_task(t4.id)["status"] == "downloading"

    completed_tasks.add(t4.id)
    time.sleep(0.2)


def test_decrease_provider_concurrency_below_active_downloads(manager, monkeypatch):
    save_settings({
        "max_concurrent": 4,
        "max_concurrent_per_provider": 2,
        "providers": [
            {
                "id": "restricted_prov",
                "name": "RestrictedProvider",
                "patterns": ["*restricted-host.com*"],
                "max_concurrent": 2
            }
        ]
    })

    executed_tasks = []
    completed_tasks = set()

    def mock_execute(task: DownloadTask):
        executed_tasks.append(task.id)
        task.status = "downloading"
        while not task.cancel_requested and task.id not in completed_tasks:
            time.sleep(0.05)
        if task.id in completed_tasks:
            task.status = "completed"
        else:
            task.status = "cancelled"

    monkeypatch.setattr(manager, "_execute_download", mock_execute)

    p1 = manager.add_task("https://stream1.restricted-host.com/vid1.mp4")
    p2 = manager.add_task("https://stream2.restricted-host.com/vid2.mp4")
    p3 = manager.add_task("https://stream3.restricted-host.com/vid3.mp4")

    assert p1.provider_id == "restricted_prov"
    assert p2.provider_id == "restricted_prov"
    assert p3.provider_id == "restricted_prov"

    time.sleep(0.9)

    assert len(executed_tasks) == 2
    assert p1.id in executed_tasks
    assert p2.id in executed_tasks
    assert manager.get_task(p3.id)["status"] == "queued"

    # Dynamically reduce restricted_prov max_concurrent from 2 down to 1
    updated_settings = {
        "max_concurrent": 4,
        "max_concurrent_per_provider": 1,
        "providers": [
            {
                "id": "restricted_prov",
                "name": "RestrictedProvider",
                "patterns": ["*restricted-host.com*"],
                "max_concurrent": 1
            }
        ]
    }
    save_settings(updated_settings)
    manager.rematch_providers(updated_settings)
    time.sleep(0.9)

    assert manager.get_task(p1.id)["status"] == "downloading"
    assert manager.get_task(p2.id)["status"] == "downloading"

    assert len(executed_tasks) == 2
    assert manager.get_task(p3.id)["status"] == "queued"

    # Complete p1: active for provider is 1 (== limit 1)
    completed_tasks.add(p1.id)
    time.sleep(0.9)
    assert manager.get_task(p1.id)["status"] == "completed"
    assert len(executed_tasks) == 2
    assert manager.get_task(p3.id)["status"] == "queued"

    # Complete p2: active for provider is 0 (< 1)
    completed_tasks.add(p2.id)
    time.sleep(0.9)
    assert manager.get_task(p2.id)["status"] == "completed"

    # Now p3 starts!
    assert len(executed_tasks) == 3
    assert p3.id in executed_tasks
    assert manager.get_task(p3.id)["status"] == "downloading"

    completed_tasks.add(p3.id)
    time.sleep(0.2)
