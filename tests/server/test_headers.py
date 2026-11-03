from typing import Any, cast

import pytest
from yt_dlp import YoutubeDL

from server.config import match_provider
from server.engine import build_ydl_options
from server.task import DownloadTask


def test_lulustream_provider_matching():
    # URL matching
    url = "https://cdn1018.cdn-tnmr.org/hls2/04/02464/aaa_h/master.m3u8?t=token&s=123"
    pid, pname, limit = match_provider(url)
    assert pid == "lulustream"
    assert pname == "LuluStream"
    assert limit == 1

    # Alternative Lulu domains
    for alt_url in [
        "https://luluvdo.com/e/abc12345",
        "https://lulustream.com/d/xyz",
        "https://lulu.st/v/444",
        "https://luluvid.com/file",
    ]:
        pid, pname, _ = match_provider(alt_url)
        assert pid == "lulustream"

    # Referer matching
    pid, pname, _ = match_provider(
        url="https://direct-storage-99.net/hls/master.m3u8",
        referer="https://luluvdo.com/e/123"
    )
    assert pid == "lulustream"


def test_build_ydl_options_default_browser_headers():
    task = DownloadTask(
        task_id="test1",
        url="https://example.com/stream.m3u8",
        title="Test Video"
    )
    opts = build_ydl_options(
        task=task,
        download_dir="C:\\Downloads",
        progress_hook=lambda d: None,
        postprocessor_hook=lambda d: None,
    )

    headers = opts["http_headers"]
    assert "User-Agent" in headers
    assert "Chrome" in headers["User-Agent"]
    assert headers["Accept"] == "*/*"
    assert headers["Sec-Fetch-Mode"] == "cors"
    assert headers["Sec-Fetch-Dest"] == "empty"
    assert opts["concurrent_fragment_downloads"] == 1


@pytest.mark.parametrize(
    ("custom_headers", "expected_language"),
    [
        pytest.param(None, "", id="no-captured-headers"),
        pytest.param({}, "", id="empty-captured-headers"),
        pytest.param({"Referer": "https://example.com/player"}, "", id="no-language"),
        pytest.param({"Accept-Language": ""}, "", id="explicit-empty"),
        pytest.param({"accept-language": ""}, "", id="lowercase-empty"),
        pytest.param({"Accept-Language": "pl-PL,pl;q=0.9"}, "pl-PL,pl;q=0.9", id="captured"),
        pytest.param({"accept-language": "en-US,en;q=0.9"}, "en-US,en;q=0.9", id="lowercase"),
        pytest.param({"ACCEPT-LANGUAGE": "de-DE"}, "de-DE", id="uppercase"),
        pytest.param({"Accept-Language": "en-GB,en;q=0.9"}, "en-GB,en;q=0.9", id="captured-firefox"),
    ],
)
def test_build_ydl_options_language_header(custom_headers, expected_language, tmp_path):
    task = DownloadTask(task_id="language-header", url="https://example.com/stream.m3u8")
    opts = build_ydl_options(
        task=task,
        download_dir=str(tmp_path),
        progress_hook=lambda d: None,
        postprocessor_hook=lambda d: None,
        custom_headers=custom_headers,
    )

    headers = opts["http_headers"]
    assert {k: v for k, v in headers.items() if k.lower() == "accept-language"} == {
        "Accept-Language": expected_language,
    }
    # Exercise yt-dlp's real default merge without making a network request.
    with YoutubeDL(cast(Any, opts)) as ydl:
        merged_headers = ydl.params["http_headers"]
        assert merged_headers is not None
        assert merged_headers["Accept-Language"] == expected_language


def test_build_ydl_options_origin_derivation_from_referer():
    task = DownloadTask(
        task_id="test2",
        url="https://storage.example.com/stream.m3u8",
        title="Test Video"
    )
    custom_headers = {
        "Referer": "https://embedplayer.org/video/12345?autoplay=1"
    }
    opts = build_ydl_options(
        task=task,
        download_dir="C:\\Downloads",
        progress_hook=lambda d: None,
        postprocessor_hook=lambda d: None,
        custom_headers=custom_headers
    )

    headers = opts["http_headers"]
    assert headers["Referer"] == "https://embedplayer.org/video/12345?autoplay=1"
    assert headers["Origin"] == "https://embedplayer.org"


def test_build_ydl_options_case_insensitive_and_custom_origin():
    task = DownloadTask(
        task_id="test3",
        url="https://example.com/stream.m3u8",
    )
    custom_headers = {
        "referer": "https://site.org/page",
        "origin": "https://custom-origin.org",
        "user-agent": "MyCustomBrowser/2.0",
        "cookie": "session=xyz123"
    }
    opts = build_ydl_options(
        task=task,
        download_dir="C:\\Downloads",
        progress_hook=lambda d: None,
        postprocessor_hook=lambda d: None,
        custom_headers=custom_headers
    )

    headers = opts["http_headers"]
    assert headers["Referer"] == "https://site.org/page"
    assert headers["Origin"] == "https://custom-origin.org"
    assert headers["User-Agent"] == "MyCustomBrowser/2.0"
    assert headers["Cookie"] == "session=xyz123"


def test_api_download_headers_propagation(client, manager):
    payload = {
        "url": "https://cdn1018.cdn-tnmr.org/hls2/test/master.m3u8",
        "title": "Lulu Video",
        "headers": {
            "Referer": "https://luluvdo.com/e/123",
            "Origin": "https://luluvdo.com",
            "User-Agent": "BrowserAgent/1.0"
        }
    }
    res = client.post("/api/download", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    task_id = data["task"]["id"]

    task = manager.tasks.get(task_id)
    assert task.headers["Referer"] == "https://luluvdo.com/e/123"
    assert task.headers["Origin"] == "https://luluvdo.com"
    assert task.headers["User-Agent"] == "BrowserAgent/1.0"
    assert task.provider_id == "lulustream"
    assert task.provider_name == "LuluStream"


def test_api_download_referer_fallback(client, manager):
    payload = {
        "url": "https://cdn1018.cdn-tnmr.org/hls2/test/master.m3u8",
        "title": "Fallback Video",
        "referer": "https://luluvdo.com/e/fallback"
    }
    res = client.post("/api/download", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    task_id = data["task"]["id"]

    task = manager.tasks.get(task_id)
    assert task.headers.get("Referer") == "https://luluvdo.com/e/fallback"
    assert task.provider_id == "lulustream"
