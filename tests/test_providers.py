import pytest

from server.config import match_provider, load_settings, save_settings
from server.downloader import DownloadManager


@pytest.fixture(autouse=True)
def setup_providers():
    save_settings({
        "max_concurrent": 3,
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


def test_doodstream_patterns():
    pid, pname, limit = match_provider("https://dood.re/e/abcdef12345")
    assert pid == "doodstream"
    assert pname == "Doodstream"
    assert limit == 1

    # CDN subdomain
    pid, pname, _ = match_provider("https://dw572mm.cloudatacdn.com/u/token123/stream.mp4")
    assert pid == "doodstream"
    assert pname == "Doodstream"


def test_elliotintel_patterns():
    # Sprintcdn / r66nv9ed.com pattern
    pid, pname, _ = match_provider("https://edge2-waw-sprintcdn.r66nv9ed.com/hls/master.m3u8")
    assert pid == "elliotintel"
    assert pname == "ElliotIntel"


def test_referer_matching():
    # Stream URL is generic/cdn-like, but embed referer points to doodstream
    pid, pname, _ = match_provider(
        url="https://192.168.1.100:8443/video.ts",
        referer="https://dood.video/e/sample"
    )
    assert pid == "doodstream"
    assert pname == "Doodstream"


def test_unrecognized_domain_fallback():
    pid, pname, limit = match_provider("https://sub.cdn.vidsource.org/stream.m3u8")
    assert pid == "vidsource.org"
    assert pname == "vidsource.org"
    assert limit == 1


def test_dynamic_custom_provider():
    settings = load_settings()
    providers = list(settings.get("providers", []))
    providers.append({
        "id": "newhost",
        "name": "NewHost",
        "patterns": ["*rotating-cdn-123.com*"],
        "max_concurrent": 2
    })
    save_settings({"providers": providers})

    pid, pname, limit = match_provider("https://node1.rotating-cdn-123.com/file.mp4")
    assert pid == "newhost"
    assert pname == "NewHost"
    assert limit == 2


def test_task_dict_includes_provider(manager):
    task = manager.add_task(
        url="https://r1148gsx.cloudatacdn.com/u/xyz/video.mp4",
        title="My Test Video"
    )
    data = task.to_dict()
    assert data["provider"] == "Doodstream"
    assert data["provider_id"] == "doodstream"
    assert data["provider_limit"] == 1


def test_rematch_providers_live_update(manager):
    task = manager.add_task(
        url="https://edge99.novelcdn.net/stream.m3u8",
        title="Novel Stream"
    )
    assert task.provider_id == "novelcdn.net"
    assert task.provider_name == "novelcdn.net"

    # Map novelcdn.net into Doodstream
    settings = load_settings()
    dood = next(p for p in settings["providers"] if p["id"] == "doodstream")
    dood["patterns"].append("*novelcdn.net*")
    save_settings(settings)

    # Rematch tasks
    manager.rematch_providers()

    assert task.provider_id == "doodstream"
    assert task.provider_name == "Doodstream"
