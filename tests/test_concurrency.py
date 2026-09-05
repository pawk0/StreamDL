import os
import sys
import unittest
import time
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.downloader import DownloadManager, DownloadTask
from server.config import save_settings


class TestConcurrency(unittest.TestCase):
    def setUp(self):
        self.manager = DownloadManager.get_instance()
        self.manager.tasks.clear()
        self.manager.task_order.clear()
        # Clean up any active threads
        self.manager._active_threads.clear()

    def tearDown(self):
        save_settings({
            "max_concurrent": 3,
            "max_concurrent_per_provider": 1,
            "providers": [
                {
                    "id": "doodstream",
                    "name": "Doodstream",
                    "patterns": ["*dood*", "*cloudatacdn.com*"],
                    "max_concurrent": 1
                }
            ],
            "default_quality": "best",
            "default_format": "mkv",
            "port": 7921
        })

    def test_queue_and_concurrency_limit(self):
        # Set max_concurrent to 2 and per_provider to 2
        save_settings({"max_concurrent": 2, "max_concurrent_per_provider": 2})

        # Mock _execute_download to simulate a long-running download without real network
        executed_tasks = []

        def mock_execute(task: DownloadTask):
            executed_tasks.append(task.id)
            task.status = "downloading"
            while not task.cancel_requested:
                time.sleep(0.05)
            task.status = "cancelled"

        with patch.object(self.manager, "_execute_download", side_effect=mock_execute):
            # Add 4 tasks
            t1 = self.manager.add_task("https://example.com/1")
            t2 = self.manager.add_task("https://example.com/2")
            t3 = self.manager.add_task("https://example.com/3")
            t4 = self.manager.add_task("https://example.com/4")

            # Wait for dispatcher loop (polls every 0.5s)
            time.sleep(0.9)

            # Check that 2 tasks are executing
            self.assertEqual(len(executed_tasks), 2)
            self.assertIn(t1.id, executed_tasks)
            self.assertIn(t2.id, executed_tasks)
            
            # Tasks 3 and 4 should still be queued
            self.assertEqual(self.manager.get_task(t3.id)["status"], "queued")
            self.assertEqual(self.manager.get_task(t4.id)["status"], "queued")

            # Now cancel task 1, freeing up a slot
            self.manager.cancel_task(t1.id)
            time.sleep(0.9)

            # Task 3 should now have started!
            self.assertEqual(len(executed_tasks), 3)
            self.assertIn(t3.id, executed_tasks)
            self.assertEqual(self.manager.get_task(t4.id)["status"], "queued")

            # Now increase concurrency from 2 to 4
            save_settings({"max_concurrent": 4, "max_concurrent_per_provider": 4})
            time.sleep(0.9)

            # Task 4 should start immediately!
            self.assertEqual(len(executed_tasks), 4)
            self.assertIn(t4.id, executed_tasks)

            # Clean up all running tasks
            for t in [t1, t2, t3, t4]:
                self.manager.cancel_task(t.id)

    def test_per_provider_concurrency_independent(self):
        # Overall max: 4, per-provider: 1 with configured test providers
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

        with patch.object(self.manager, "_execute_download", side_effect=mock_execute):
            # Task 1: Doodstream CDN
            t1 = self.manager.add_task("https://dw572mm.cloudatacdn.com/video1.mp4")
            # Task 2: Also Doodstream CDN (should be throttled because dood limit is 1)
            t2 = self.manager.add_task("https://r1148gsx.cloudatacdn.com/video2.mp4")
            # Task 3: ElliotIntel (should run concurrently with Task 1!)
            t3 = self.manager.add_task("https://edge2-waw-sprintcdn.r66nv9ed.com/stream.m3u8")
            # Task 4: Another Player option (should also run concurrently!)
            t4 = self.manager.add_task("https://anotheroption.tv/video4.m3u8")

            # Verify provider classification
            self.assertEqual(t1.provider_name, "Doodstream")
            self.assertEqual(t2.provider_name, "Doodstream")
            self.assertEqual(t3.provider_name, "ElliotIntel")
            self.assertIn("anotheroption", t4.provider_name.lower())

            # Wait for dispatcher tick
            time.sleep(0.9)

            # t1 (Dood), t3 (Elliot), t4 (Another) should all be downloading!
            self.assertEqual(len(executed_tasks), 3)
            self.assertIn(t1.id, executed_tasks)
            self.assertIn(t3.id, executed_tasks)
            self.assertIn(t4.id, executed_tasks)

            # t2 (second Doodstream) must still be queued because Doodstream limit is 1!
            self.assertNotIn(t2.id, executed_tasks)
            self.assertEqual(self.manager.get_task(t2.id)["status"], "queued")

            # Now cancel t1 (first Doodstream)
            self.manager.cancel_task(t1.id)
            time.sleep(0.9)

            # t2 should now have started!
            self.assertIn(t2.id, executed_tasks)
            self.assertEqual(len(executed_tasks), 4)

            for t in [t1, t2, t3, t4]:
                self.manager.cancel_task(t.id)


if __name__ == "__main__":
    unittest.main()
