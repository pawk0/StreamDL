import pytest

from server.config import load_settings, match_provider, save_settings


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


def test_load_settings_corrupted_json(tmp_path, monkeypatch):
    corrupt_file = tmp_path / "corrupt_settings.json"
    corrupt_file.write_text("{invalid json syntax!!!", encoding="utf-8")
    monkeypatch.setenv("VIDEO_DL_SETTINGS_FILE", str(corrupt_file))
    monkeypatch.delenv("VIDEO_DL_PORT", raising=False)
    settings = load_settings()
    assert settings["port"] == 7921
    assert "download_dir" in settings


def test_invalid_port_env_variable(monkeypatch):
    monkeypatch.setenv("VIDEO_DL_PORT", "not_a_number")
    settings = load_settings()
    assert isinstance(settings["port"], int)


@pytest.mark.parametrize("raw_provider, expected_patterns, expected_limit", [
    (
        {"name": "StringPatterns", "patterns": "alpha.com, beta.com", "max_concurrent": "invalid"},
        ["alpha.com", "beta.com"],
        1,
    ),
    (
        {"name": "DefaultConcurrency", "patterns": ["gamma.com"], "max_concurrent": None},
        ["gamma.com"],
        1,
    ),
    (
        {"name": "RawList", "patterns": 12345},
        [],
        1,
    ),
])
def test_save_settings_provider_sanitization(raw_provider, expected_patterns, expected_limit):
    saved = save_settings({"providers": [raw_provider]})
    p = saved["providers"][0]
    assert p["patterns"] == expected_patterns
    assert p["max_concurrent"] == expected_limit


@pytest.mark.parametrize("invalid_item", [
    {"name": ""},
    {"name": "   "},
    "non-dict-entry",
    None,
])
def test_save_settings_skips_invalid_providers(invalid_item):
    saved = save_settings({"providers": [invalid_item]})
    assert not any(
        isinstance(p, dict) and p.get("name", "").strip() == ""
        for p in saved["providers"]
    )


@pytest.mark.parametrize("url, provider_config, expected_pid", [
    ("http://localhost:8080/stream.m3u8", None, "localhost"),
    (
        "https://sub.plainword.net/video.mp4",
        [{"id": "plainpattern", "name": "PlainPattern", "patterns": ["plainword.net"], "max_concurrent": 1}],
        "plainpattern",
    ),
    (
        "https://anydomain.com/video.mp4",
        [{"id": "emptypat", "name": "EmptyPat", "patterns": ["", "  "], "max_concurrent": 1}],
        "anydomain.com",
    ),
])
def test_match_provider_domain_edge_cases(url, provider_config, expected_pid):
    if provider_config is not None:
        save_settings({"providers": provider_config})
    pid, _, _ = match_provider(url)
    assert pid == expected_pid


@pytest.mark.parametrize("invalid_setting", [
    {"max_concurrent": "not_an_int"},
    {"download_dir": "   "},
])
def test_save_settings_global_invalid_values_skipped(invalid_setting):
    original = load_settings()
    saved = save_settings(invalid_setting)
    for k in invalid_setting:
        assert saved[k] == original[k]



