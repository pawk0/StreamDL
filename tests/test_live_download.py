import os
import sys
import unittest
import time
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.downloader import DownloadManager
from server.config import save_settings

class TestLiveDownload(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.abspath(f"test_downloads_{int(time.time())}")
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)
        os.makedirs(self.test_dir, exist_ok=True)
        save_settings({
            "download_dir": self.test_dir,
            "max_concurrent": 2
        })
        self.manager = DownloadManager.get_instance()
        self.manager.tasks.clear()
        self.manager.task_order.clear()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_hls_stream_download(self):
        # Lightweight test stream that completes in a few seconds
        url = "https://test-streams.mux.dev/test_001/stream.m3u8"
        task = self.manager.add_task(
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
            t = self.manager.get_task(task.id)
            if t["status"] == "completed":
                completed = True
                break
            elif t["status"] == "failed":
                self.fail(f"Download failed: {t.get('error_message')}")

        self.assertTrue(completed, "Download did not complete within timeout")
        t = self.manager.get_task(task.id)
        self.assertIsNotNone(t["filepath"])
        self.assertTrue(os.path.exists(t["filepath"]))
        self.assertGreater(os.path.getsize(t["filepath"]), 100000)
        print(f"Downloaded test file: {t['filepath']} ({os.path.getsize(t['filepath'])} bytes)")


if __name__ == "__main__":
    unittest.main()
