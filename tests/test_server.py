import os
import sys
import unittest
import json
import time

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.app import app
from server.downloader import DownloadManager
from server.config import load_settings, save_settings


class TestServerAPI(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.manager = DownloadManager.get_instance()
        # Reset tasks
        self.manager.tasks.clear()
        self.manager.task_order.clear()

    def test_status_endpoint(self):
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "online")
        self.assertIn("max_concurrent", data)
        self.assertIn("download_dir", data)
        self.assertEqual(data["active_count"], 0)

    def test_settings_get_and_post(self):
        # Update settings
        new_settings = {
            "max_concurrent": 4,
            "default_quality": "720p",
            "default_format": "mkv"
        }
        res = self.client.post(
            "/api/settings",
            data=json.dumps(new_settings),
            content_type="application/json"
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["settings"]["max_concurrent"], 4)
        self.assertEqual(data["settings"]["default_quality"], "720p")

        # Verify get settings returns updated values
        res_get = self.client.get("/api/settings")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.get_json()["settings"]["max_concurrent"], 4)

    def test_download_endpoint_validation(self):
        # Test missing url
        res = self.client.post(
            "/api/download",
            data=json.dumps({}),
            content_type="application/json"
        )
        self.assertEqual(res.status_code, 400)

        # Test valid url queuing
        res = self.client.post(
            "/api/download",
            data=json.dumps({
                "url": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
                "title": "Big Buck Bunny HLS",
                "quality": "720p",
                "format": "mp4"
            }),
            content_type="application/json"
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["task"]["title"], "Big Buck Bunny HLS")
        task_id = data["task"]["id"]

        # Check queue
        res_queue = self.client.get("/api/queue")
        self.assertEqual(res_queue.status_code, 200)
        q_data = res_queue.get_json()
        self.assertEqual(len(q_data["tasks"]), 1)
        self.assertEqual(q_data["tasks"][0]["id"], task_id)

    def test_cancellation(self):
        # Add task
        task = self.manager.add_task(
            url="https://example.com/fake.m3u8",
            title="Fake Task"
        )
        self.assertEqual(task.status, "queued")

        # Cancel task
        res = self.client.post(f"/api/cancel/{task.id}")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])

        updated = self.manager.get_task(task.id)
        self.assertEqual(updated["status"], "cancelled")

    def test_clear_finished(self):
        task = self.manager.add_task(url="https://example.com/fake.m3u8")
        self.manager.cancel_task(task.id)

        res = self.client.post("/api/clear")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(self.manager.get_all_tasks()), 0)

    def test_title_sanitization_and_generic_check(self):
        from server.downloader import sanitize_filename, is_generic_title
        
        # Test sanitization of forbidden Windows characters
        dirty_title = 'My Video: "Episode 1" <HD> / 2026? *special* | [m3u8]'
        clean = sanitize_filename(dirty_title)
        for char in '<>:"/\\|?*':
            self.assertNotIn(char, clean)
        self.assertEqual(clean, "My Video Episode 1 HD 2026 special [m3u8]")

        # Test generic title detection
        self.assertTrue(is_generic_title("master"))
        self.assertTrue(is_generic_title("index"))
        self.assertTrue(is_generic_title("index-f2-v1-a1"))
        self.assertTrue(is_generic_title("manifest"))
        self.assertFalse(is_generic_title("Eliota Intelligence Analysis"))

    def test_doodstream_url_detection(self):
        from server.downloader import is_doodstream_url
        self.assertTrue(is_doodstream_url("https://dood.re/e/xyz123"))
        self.assertTrue(is_doodstream_url("https://doodstream.com/d/abc456"))
        self.assertTrue(is_doodstream_url("https://dood.to/e/789"))
        self.assertFalse(is_doodstream_url("https://youtube.com/watch?v=123"))


if __name__ == "__main__":
    unittest.main()
