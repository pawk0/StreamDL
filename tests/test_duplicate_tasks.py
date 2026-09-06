import concurrent.futures
import http.server
import json
import os
import threading

import pytest

from server.downloader import DuplicateTaskError
from server.engine import execute_download
from server.task import DownloadTask
from server.utils import get_unique_base, sanitize_filename


class SimpleVideoHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", "100000")
        self.end_headers()
        self.wfile.write(b"\x00" * 100000)


@pytest.fixture(scope="module")
def video_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), SimpleVideoHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/video.mp4"
    server.shutdown()


def test_reproduce_duplicate_filename_collision_and_fix(manager, isolated_env, video_server):
    """
    Reproduction & Resolution Test:
    Demonstrates that without unique base derivation, downloading to an open/locked file
    fails on Windows with WinError 32.
    With enqueue-time disambiguation, the second task is automatically renamed to
    'vid_example (1)' and downloads cleanly alongside the locked file without errors.
    """
    download_dir = isolated_env["download_dir"]

    # 1. Enqueue and execute Task 1
    t1 = manager.add_task(url=video_server, title="vid_example")
    assert t1.title == "vid_example"
    execute_download(t1, download_dir=str(download_dir))
    assert t1.status == "completed"
    assert t1.filepath and os.path.exists(t1.filepath)

    # 2. Simulate file being locked in-use (e.g. by Windows Explorer thumbnailing or a media player)
    with open(t1.filepath, "rb"):
        # Demonstrate root cause: on Windows, renaming a .part file over a locked destination raises WinError 32
        fake_part = os.path.join(download_dir, "vid_example.mp4.part")
        with open(fake_part, "wb") as pf:
            pf.write(b"part_data")
        try:
            with pytest.raises(PermissionError) as exc_info:
                os.replace(fake_part, t1.filepath)
            assert "WinError 32" in str(exc_info.value) or "Access is denied" in str(exc_info.value)
        finally:
            if os.path.exists(fake_part):
                os.remove(fake_part)

        # 3. Enqueuing through the manager with a different URL auto-disambiguates at enqueue time:
        t2 = manager.add_task(url=f"{video_server}?alt=1", title="vid_example")
        assert t2.title == "vid_example (1)"

        # Execute t2: downloads cleanly to vid_example (1).mp4 alongside locked file without collision or error
        execute_download(t2, download_dir=str(download_dir))
        assert t2.status == "completed"
        assert t2.filepath and os.path.exists(t2.filepath)
        assert os.path.basename(t2.filepath).startswith("vid_example (1)")


def test_same_name_same_url_rejected(manager, client):
    """Same name + same URL must be rejected with 409 Conflict."""
    url = "https://example.com/clip.mp4"
    title = "My Cool Video"

    # Enqueue first task
    res1 = client.post(
        "/api/download",
        data=json.dumps({"url": url, "title": title}),
        content_type="application/json"
    )
    assert res1.status_code == 200
    assert res1.get_json()["success"] is True

    # Enqueue duplicate task with same name and same URL -> 409 Conflict
    res2 = client.post(
        "/api/download",
        data=json.dumps({"url": url, "title": title}),
        content_type="application/json"
    )
    assert res2.status_code == 409
    data2 = res2.get_json()
    assert data2["success"] is False
    assert "already queued or downloading" in data2["error"]

    # Verify direct call to manager.add_task also raises DuplicateTaskError
    with pytest.raises(DuplicateTaskError):
        manager.add_task(url=url, title=title)


def test_generic_title_same_url_rejected(manager, client):
    """No title (generic) + same URL must be rejected with 409 Conflict."""
    url = "https://example.com/stream.m3u8"

    res1 = client.post(
        "/api/download",
        data=json.dumps({"url": url}),
        content_type="application/json"
    )
    assert res1.status_code == 200

    res2 = client.post(
        "/api/download",
        data=json.dumps({"url": url}),
        content_type="application/json"
    )
    assert res2.status_code == 409
    assert "already queued or downloading" in res2.get_json()["error"]


def test_same_name_different_url_disambiguated(manager, client):
    """Same name + different URL must be renamed to f'{base_name} (1)', (2), etc."""
    title = "Shared Title"

    t1 = manager.add_task(url="https://example.com/video1", title=title)
    assert t1.title == "Shared Title"

    # Second task with different URL is renamed to "Shared Title (1)"
    res2 = client.post(
        "/api/download",
        data=json.dumps({"url": "https://example.com/video2", "title": title}),
        content_type="application/json"
    )
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2["task"]["title"] == "Shared Title (1)"

    # Third task with another different URL is renamed to "Shared Title (2)"
    res3 = client.post(
        "/api/download",
        data=json.dumps({"url": "https://example.com/video3", "title": title}),
        content_type="application/json"
    )
    assert res3.status_code == 200
    data3 = res3.get_json()
    assert data3["task"]["title"] == "Shared Title (2)"


@pytest.mark.parametrize("title_a, title_b", [
    ("vid:example?", "vid/example*"),
    ("<vid>|example", "videxample"),
    ("  my video  ", "my video"),
    ("..cool video..", "cool video"),
])
def test_sanitized_name_collision_detection(manager, title_a, title_b):
    """Duplicate detection must operate on sanitized filenames, not raw titles."""
    url1 = "https://example.com/v1"
    url2 = "https://example.com/v2"

    _ = manager.add_task(url=url1, title=title_a)
    clean_a = sanitize_filename(title_a)

    # Same URL with differing unsanitized characters that sanitize identically -> Conflict
    with pytest.raises(DuplicateTaskError):
        manager.add_task(url=url1, title=title_b)

    # Different URL with differing unsanitized characters that sanitize identically -> Disambiguated
    t2 = manager.add_task(url=url2, title=title_b)
    assert t2.title == f"{clean_a} (1)"


def test_case_insensitivity_collision(manager):
    """Titles differing only in case must be detected as colliding on Windows."""
    url1 = "https://example.com/v1"
    url2 = "https://example.com/v2"

    t1 = manager.add_task(url=url1, title="Vid_Example")
    assert t1.title == "Vid_Example"

    # Same URL differing in case -> Conflict
    with pytest.raises(DuplicateTaskError):
        manager.add_task(url=url1, title="VID_EXAMPLE")

    # Different URL differing in case -> Disambiguated
    t2 = manager.add_task(url=url2, title="vid_example")
    assert t2.title == "vid_example (1)"


def test_cancelled_task_releases_reservation(manager):
    """Cancelling an active task must release its name reservation."""
    url1 = "https://example.com/v1"
    url2 = "https://example.com/v2"
    title = "Burned Title"

    t1 = manager.add_task(url=url1, title=title)
    assert t1.title == "Burned Title"
    assert t1.id in manager._reserved_names

    # Cancel task 1
    assert manager.cancel_task(t1.id) is True
    assert t1.id not in manager._reserved_names

    # Enqueuing new task can reuse the title without burning it
    t2 = manager.add_task(url=url2, title=title)
    assert t2.title == "Burned Title"


def test_failed_task_releases_reservation(manager):
    """Failing a task releases its name reservation."""
    title = "Failing Task"
    t1 = manager.add_task(url="https://example.com/fail", title=title)
    assert t1.title == "Failing Task"

    # Mark failed and execute cleanup loop logic
    t1.status = "failed"
    # Calling add_task will prune dead reservations
    t2 = manager.add_task(url="https://example.com/retry", title=title)
    assert t2.title == "Failing Task"


def test_disk_file_preserves_unavailability(isolated_env, manager):
    """Existing files on disk keep the name unavailable even if not in memory."""
    download_dir = isolated_env["download_dir"]

    # Pre-create a file on disk
    existing_file = download_dir / "already_done.mp4"
    existing_file.write_bytes(b"data")

    # Add task with the same name
    t = manager.add_task(url="https://example.com/new", title="already_done")
    assert t.title == "already_done (1)"


@pytest.mark.parametrize("existing_names, target_base, expected", [
    ([], "video", "video"),
    (["video.mp4"], "video", "video (1)"),
    (["video.mp4", "video (1).mp4"], "video", "video (2)"),
    (["video.final.mp4"], "video", "video"),
    (["video_other.mp4"], "video", "video"),
    (["video.f137.mp4"], "video", "video (1)"),
    (["VID_TEST.mkv"], "vid_test", "vid_test (1)"),
])
def test_get_unique_base_boundaries(tmp_path, existing_names, target_base, expected):
    """Parametrized boundary tests for get_unique_base against disk collisions."""
    test_dir = tmp_path / "unique_test"
    test_dir.mkdir(parents=True, exist_ok=True)
    for name in existing_names:
        (test_dir / name).write_bytes(b"x")

    result = get_unique_base(str(test_dir), target_base)
    assert result == expected


def test_long_title_truncation_collision(manager):
    """
    Long titles (>= 150 chars) must not collide when appended with '(1)'.
    The base name must be trimmed so that the full disambiguated candidate stays <= 150 chars,
    preventing sanitize_filename from truncating the '(1)' suffix and colliding on disk.
    """
    long_title = "a" * 150
    t1 = manager.add_task(url="https://example.com/long1", title=long_title)
    assert len(t1.title) == 150

    t2 = manager.add_task(url="https://example.com/long2", title=long_title)
    assert t2.title.endswith(" (1)")
    assert len(t2.title) <= 150
    # Sanitize must not strip the disambiguation suffix
    assert sanitize_filename(t2.title) == t2.title
    assert t2.title != t1.title


@pytest.mark.parametrize("url_a, url_b", [
    ("https://example.com/video/", "https://example.com/video"),
    ("HTTPS://EXAMPLE.COM/video", "https://example.com/video"),
    ("https://example.com/watch?v=123", "HTTPS://EXAMPLE.COM/watch?v=123"),
])
def test_url_normalization_variations_rejected(manager, url_a, url_b):
    """URLs differing only in case, scheme casing, or trailing slash must be detected as duplicates."""
    title = "Normalize URL Video"
    manager.add_task(url=url_a, title=title)

    with pytest.raises(DuplicateTaskError):
        manager.add_task(url=url_b, title=title)


def test_pre_existing_parentheses_treated_as_immutable_stem(manager):
    """
    Titles containing numbers in parentheses (e.g. 'Episode (1)', 'Blink (182)', 'Area (51)')
    are treated as immutable base stems. Disambiguation appends ' (1)', ' (2)', etc.
    rather than mutating title content or falsely impersonating 'Episode (2)'.
    """
    title = "Episode (1)"
    t1 = manager.add_task(url="https://example.com/ep1", title=title)
    assert t1.title == "Episode (1)"

    t2 = manager.add_task(url="https://example.com/ep2", title=title)
    assert t2.title == "Episode (1) (1)"

    t3 = manager.add_task(url="https://example.com/ep3", title=title)
    assert t3.title == "Episode (1) (2)"


def test_dotted_title_not_falsely_collided(tmp_path):
    """
    A file on disk with dots in the name (e.g. 'v1.0.mp4') must not falsely collide
    with a task titled 'v1' because '.0' is part of the stem, not the extension.
    """
    test_dir = tmp_path / "dot_test"
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "v1.0.mp4").write_bytes(b"data")

    # 'v1' should NOT collide with 'v1.0.mp4'
    assert get_unique_base(str(test_dir), "v1") == "v1"

    # But if 'v1.mp4' actually exists, it MUST collide
    (test_dir / "v1.mp4").write_bytes(b"data")
    assert get_unique_base(str(test_dir), "v1") == "v1 (1)"


def test_concurrent_enqueue_race_condition_different_urls(manager):
    """Stress test: 20 threads simultaneously enqueuing tasks with the same title and different URLs."""
    title = "Concurrent Stress Test"
    num_threads = 20

    def enqueue(idx):
        return manager.add_task(url=f"https://example.com/stress/{idx}", title=title)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(enqueue, i) for i in range(num_threads)]
        tasks = [f.result() for f in concurrent.futures.as_completed(futures)]

    titles = [t.title for t in tasks]
    assert len(titles) == num_threads
    # All 20 titles must be completely distinct
    assert len(set(titles)) == num_threads
    assert title in titles
    for i in range(1, num_threads):
        assert f"{title} ({i})" in titles


def test_concurrent_enqueue_race_condition_same_url(manager):
    """Stress test: 10 threads simultaneously enqueuing tasks with the same title and identical URL."""
    title = "Duplicate Race Test"
    url = "https://example.com/race_exact"
    num_threads = 10

    def enqueue():
        return manager.add_task(url=url, title=title)

    successes = []
    failures = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(enqueue) for _ in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            try:
                task = f.result()
                successes.append(task)
            except DuplicateTaskError as e:
                failures.append(e)

    # Exactly one thread succeeds; the other 9 must be rejected with DuplicateTaskError
    assert len(successes) == 1
    assert len(failures) == num_threads - 1


def test_extracted_title_collision_prevention(isolated_env, video_server):
    """
    When a task is added without title (e.g. web UI flow where title=None),
    and the extracted title matches an existing locked file on disk,
    execute_download must disambiguate the title and output template to prevent WinError 32.
    """
    download_dir = isolated_env["download_dir"]

    # Pre-create an existing file on disk and lock it
    existing_file = download_dir / "video.mp4"
    existing_file.write_bytes(b"existing_data")

    with open(existing_file, "rb"):
        # Queue task with title=None (generic)
        task = DownloadTask(task_id="ext1", url=video_server, title=None)
        execute_download(task, download_dir=str(download_dir))

        assert task.status == "completed"
        # Must have disambiguated to video (1) and avoided colliding with locked video.mp4
        assert task.title == "video (1)"
        assert task.filepath and os.path.exists(task.filepath)
        assert os.path.basename(task.filepath).startswith("video (1)")


def test_symbols_only_title_same_url_rejected(manager):
    """
    Titles consisting purely of punctuation or symbols (e.g. ':::***???')
    sanitize to 'video' and are recognized as generic placeholders.
    Adding a duplicate task for the same URL must be rejected with DuplicateTaskError.
    """
    url = "https://example.com/symbols_stream"
    t1 = manager.add_task(url=url, title=":::***???")
    # Symbols-only title is generic, so title remains as provided or None without reserving 'video'
    assert t1.id not in manager._reserved_names

    with pytest.raises(DuplicateTaskError):
        manager.add_task(url=url, title=":::***???")

    # Also rejected if second attempt passes None or explicit generic title 'video'
    with pytest.raises(DuplicateTaskError):
        manager.add_task(url=url, title=None)

    with pytest.raises(DuplicateTaskError):
        manager.add_task(url=url, title="video")


def test_symbols_only_title_different_url_allowed(manager):
    """
    Two tasks with symbols-only titles and different URLs must both be allowed
    without premature filename reservation or collision at enqueue time.
    """
    t1 = manager.add_task(url="https://example.com/stream1", title="???")
    t2 = manager.add_task(url="https://example.com/stream2", title="***")
    assert t1.id in manager.tasks
    assert t2.id in manager.tasks


def test_trailing_dots_and_spaces_in_title_detected_as_duplicate(manager):
    """
    Windows filesystem forbids trailing dots and spaces in filenames.
    Titles differing only in trailing dots or spaces sanitize to the same base name.
    """
    url1 = "https://example.com/dots1"
    url2 = "https://example.com/dots2"

    t1 = manager.add_task(url=url1, title="my video...   ")
    assert t1.title == "my video"

    # Same URL with different trailing dots/spaces -> duplicate rejection
    with pytest.raises(DuplicateTaskError):
        manager.add_task(url=url1, title="my video.")

    # Different URL with trailing dots -> disambiguated
    t2 = manager.add_task(url=url2, title="my video.")
    assert t2.title == "my video (1)"


def test_movie_year_in_parentheses_not_incremented(tmp_path):
    """
    4-digit release years (1900-2099) in parentheses like 'Inception (2010)'
    are title content, NOT duplicate counters.
    Disambiguation must append ' (1)', yielding 'Inception (2010) (1)' rather than 'Inception (2011)'.
    A second duplicate of 'Inception (2010) (1)' must increment the counter to 'Inception (2010) (2)'.
    """
    test_dir = str(tmp_path)
    res = get_unique_base(test_dir, "Inception (2010)", reserved_names={"inception (2010)"})
    assert res == "Inception (2010) (1)"

    res2 = get_unique_base(
        test_dir,
        "Inception (2010)",
        reserved_names={"inception (2010)", "inception (2010) (1)"}
    )
    assert res2 == "Inception (2010) (2)"


def test_intermediate_fragment_files_on_disk_trigger_disambiguation(tmp_path):
    """
    Fragment files (*-Frag*.part) and intermediate format streams (*.fba.*, *.f137.*)
    left on disk by in-progress or interrupted downloads must trigger disambiguation.
    """
    test_dir = tmp_path / "frag_dir"
    test_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fragment file on disk
    (test_dir / "stream.mp4.part-Frag0.part").write_bytes(b"data")
    assert get_unique_base(str(test_dir), "stream") == "stream (1)"

    # 2. Intermediate format stream file on disk
    (test_dir / "audio.fba.m4a").write_bytes(b"data")
    assert get_unique_base(str(test_dir), "audio") == "audio (1)"

    # 3. Intermediate dash video format on disk
    (test_dir / "hd.fdash-video.mp4").write_bytes(b"data")
    assert get_unique_base(str(test_dir), "hd") == "hd (1)"


def test_completed_task_allows_redownload_with_disambiguation(isolated_env, manager):
    """
    Once a task transitions to 'completed', re-enqueuing the same URL and title
    must NOT raise DuplicateTaskError (active duplicate check only applies to queued/downloading/processing).
    Instead, because the completed file exists on disk, the new task is disambiguated to f'{title} (1)'.
    """
    download_dir = isolated_env["download_dir"]
    url = "https://example.com/finish_video"
    title = "Finished Video"

    t1 = manager.add_task(url=url, title=title)
    # Simulate completion and file creation on disk
    t1.status = "completed"
    file_path = download_dir / f"{title}.mp4"
    file_path.write_bytes(b"data")
    t1.filepath = str(file_path)
    t1.filename = f"{title}.mp4"

    # Re-adding the same URL and title is allowed and safely disambiguates
    t2 = manager.add_task(url=url, title=title)
    assert t2.status == "queued"
    assert t2.title == f"{title} (1)"


def test_task_in_processing_state_rejects_duplicate(manager):
    """
    A task in 'processing' state (e.g. ffmpeg postprocessing or finalizing)
    is still active and must reject identical tasks with 409 DuplicateTaskError.
    """
    url = "https://example.com/processing_video"
    title = "Muxing Video"

    t1 = manager.add_task(url=url, title=title)
    t1.status = "processing"

    with pytest.raises(DuplicateTaskError):
        manager.add_task(url=url, title=title)

    # Different URL is disambiguated
    t2 = manager.add_task(url=f"{url}_alt", title=title)
    assert t2.title == f"{title} (1)"


def test_unicode_titles_preserved_and_disambiguated(manager, tmp_path):
    """Non-ASCII and Unicode titles across languages must be preserved and disambiguated cleanly."""
    # Japanese
    t_jp1 = manager.add_task(url="https://example.com/jp1", title="アニメ")
    assert t_jp1.title == "アニメ"
    t_jp2 = manager.add_task(url="https://example.com/jp2", title="アニメ")
    assert t_jp2.title == "アニメ (1)"

    # Polish
    t_pl1 = manager.add_task(url="https://example.com/pl1", title="Żółw")
    assert t_pl1.title == "Żółw"
    t_pl2 = manager.add_task(url="https://example.com/pl2", title="Żółw")
    assert t_pl2.title == "Żółw (1)"

    # Cyrillic
    t_cy1 = manager.add_task(url="https://example.com/cy1", title="Видео")
    assert t_cy1.title == "Видео"
    t_cy2 = manager.add_task(url="https://example.com/cy2", title="Видео")
    assert t_cy2.title == "Видео (1)"


def test_case_insensitive_file_extensions_on_disk(tmp_path):
    """Files with uppercase extensions on disk (e.g. .MP4, .MKV) must collide with target base."""
    test_dir = tmp_path / "upper_ext"
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "my_clip.MP4").write_bytes(b"data")

    assert get_unique_base(str(test_dir), "my_clip") == "my_clip (1)"


def test_multi_digit_counter_boundary_and_length_truncation(tmp_path):
    """
    When the counter reaches 10 or more digits on a title near the 150-char limit,
    the candidate must not exceed 150 characters and must not chop off the counter suffix.
    """
    test_dir = str(tmp_path)
    base = "x" * 150

    # Simulate existing reservations from (1) through (9)
    reserved = {sanitize_filename(base).lower()}
    for i in range(1, 10):
        suffix = f" ({i})"
        max_stem = 150 - len(suffix)
        reserved.add(f"{base[:max_stem]}{suffix}".lower())

    # Candidate 10 will have suffix ' (10)' (7 chars)
    candidate_10 = get_unique_base(test_dir, base, reserved_names=reserved)
    assert candidate_10.endswith(" (10)")
    assert len(candidate_10) <= 150
    assert sanitize_filename(candidate_10) == candidate_10


def test_clear_finished_preserves_active_task_reservations(manager):
    """
    Calling manager.clear_finished() must purge completed/failed tasks
    while preserving active (queued/downloading) tasks and their name reservations.
    """
    t_active = manager.add_task(url="https://example.com/active", title="Active Task")
    t_failed = manager.add_task(url="https://example.com/failed", title="Failed Task")
    t_completed = manager.add_task(url="https://example.com/completed", title="Completed Task")

    t_failed.status = "failed"
    t_completed.status = "completed"

    manager.clear_finished()

    # Active task remains in tasks and _reserved_names
    assert t_active.id in manager.tasks
    assert t_active.id in manager._reserved_names
    assert t_failed.id not in manager.tasks
    assert t_completed.id not in manager.tasks

    # Duplicate of active task is still rejected
    with pytest.raises(DuplicateTaskError):
        manager.add_task(url="https://example.com/active", title="Active Task")


def test_download_api_endpoints_409_and_400(client):
    """
    Both /api/download and /download endpoints must return 409 on duplicates
    and 400 on missing/empty URL parameter.
    """
    url = "https://example.com/api_test_clip"
    title = "API Test Video"

    # 1. Missing URL -> 400 Bad Request
    res_bad1 = client.post("/api/download", data=json.dumps({}), content_type="application/json")
    assert res_bad1.status_code == 400

    res_bad2 = client.post("/download", data=json.dumps({"url": "   "}), content_type="application/json")
    assert res_bad2.status_code == 400

    # 2. First enqueue via /download
    res1 = client.post(
        "/download",
        data=json.dumps({"url": url, "title": title}),
        content_type="application/json"
    )
    assert res1.status_code == 200

    # 3. Duplicate enqueue via /download -> 409 Conflict
    res2 = client.post(
        "/download",
        data=json.dumps({"url": url, "title": title}),
        content_type="application/json"
    )
    assert res2.status_code == 409
    assert res2.get_json()["success"] is False

    # 4. Duplicate enqueue via /api/download -> 409 Conflict
    res3 = client.post(
        "/api/download",
        data=json.dumps({"url": url, "title": title}),
        content_type="application/json"
    )
    assert res3.status_code == 409
    assert res3.get_json()["success"] is False


def test_get_unique_base_with_nonexistent_or_none_download_dir():
    """get_unique_base must handle None or non-existent download_dir without raising exceptions."""
    assert get_unique_base(None, "my_video") == "my_video"
    assert get_unique_base(None, "my_video", reserved_names={"my_video"}) == "my_video (1)"
    assert get_unique_base("C:/non_existent_folder_abc123/xyz", "my_video") == "my_video"


def test_url_with_whitespace_normalized(manager):
    """URLs with leading or trailing whitespace must be normalized and detected as duplicate."""
    url = "https://example.com/whitespace_video"
    title = "Whitespace Test"

    manager.add_task(url=f"  {url}  ", title=title)

    with pytest.raises(DuplicateTaskError):
        manager.add_task(url=url, title=title)


