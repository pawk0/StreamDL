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

    def test_decrease_global_concurrency_below_active_downloads(self):
        # Start with max_concurrent: 3
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

        with patch.object(self.manager, "_execute_download", side_effect=mock_execute):
            t1 = self.manager.add_task("https://example.com/1")
            t2 = self.manager.add_task("https://example.com/2")
            t3 = self.manager.add_task("https://example.com/3")
            t4 = self.manager.add_task("https://example.com/4")

            # Wait for dispatcher loop to start tasks up to initial limit of 3
            time.sleep(0.9)

            self.assertEqual(len(executed_tasks), 3)
            self.assertIn(t1.id, executed_tasks)
            self.assertIn(t2.id, executed_tasks)
            self.assertIn(t3.id, executed_tasks)
            self.assertEqual(self.manager.get_task(t4.id)["status"], "queued")

            # Dynamically decrease max_concurrent from 3 down to 1
            save_settings({"max_concurrent": 1, "max_concurrent_per_provider": 3})
            time.sleep(0.9)

            # Active downloads must NOT be cancelled or interrupted
            self.assertEqual(self.manager.get_task(t1.id)["status"], "downloading")
            self.assertEqual(self.manager.get_task(t2.id)["status"], "downloading")
            self.assertEqual(self.manager.get_task(t3.id)["status"], "downloading")

            # t4 must STILL be queued because active count (3) exceeds new max_concurrent (1)
            self.assertEqual(len(executed_tasks), 3)
            self.assertEqual(self.manager.get_task(t4.id)["status"], "queued")

            # Complete task 1: active downloads drops to 2 (still > new limit of 1)
            completed_tasks.add(t1.id)
            time.sleep(0.9)
            self.assertEqual(self.manager.get_task(t1.id)["status"], "completed")
            self.assertEqual(len(executed_tasks), 3)
            self.assertEqual(self.manager.get_task(t4.id)["status"], "queued")

            # Complete task 2: active downloads drops to 1 (still >= new limit of 1)
            completed_tasks.add(t2.id)
            time.sleep(0.9)
            self.assertEqual(self.manager.get_task(t2.id)["status"], "completed")
            self.assertEqual(len(executed_tasks), 3)
            self.assertEqual(self.manager.get_task(t4.id)["status"], "queued")

            # Complete task 3: active downloads drops to 0 (now < new limit of 1)
            completed_tasks.add(t3.id)
            time.sleep(0.9)
            self.assertEqual(self.manager.get_task(t3.id)["status"], "completed")

            # Now task 4 should have been picked up and started!
            self.assertEqual(len(executed_tasks), 4)
            self.assertIn(t4.id, executed_tasks)
            self.assertEqual(self.manager.get_task(t4.id)["status"], "downloading")

            # Clean up
            completed_tasks.add(t4.id)
            time.sleep(0.2)

    def test_decrease_provider_concurrency_below_active_downloads(self):
        # Global max: 4, custom provider initial limit: 2
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

        with patch.object(self.manager, "_execute_download", side_effect=mock_execute):
            p1 = self.manager.add_task("https://stream1.restricted-host.com/vid1.mp4")
            p2 = self.manager.add_task("https://stream2.restricted-host.com/vid2.mp4")
            p3 = self.manager.add_task("https://stream3.restricted-host.com/vid3.mp4")

            self.assertEqual(p1.provider_id, "restricted_prov")
            self.assertEqual(p2.provider_id, "restricted_prov")
            self.assertEqual(p3.provider_id, "restricted_prov")

            # Wait for dispatcher to start p1 and p2 (up to provider limit 2)
            time.sleep(0.9)

            self.assertEqual(len(executed_tasks), 2)
            self.assertIn(p1.id, executed_tasks)
            self.assertIn(p2.id, executed_tasks)
            self.assertEqual(self.manager.get_task(p3.id)["status"], "queued")

            # Now dynamically reduce restricted_prov max_concurrent from 2 down to 1
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
            self.manager.rematch_providers(updated_settings)
            time.sleep(0.9)

            # Both active downloads continue running uninterrupted
            self.assertEqual(self.manager.get_task(p1.id)["status"], "downloading")
            self.assertEqual(self.manager.get_task(p2.id)["status"], "downloading")

            # p3 must remain queued because active for provider (2) >= new provider limit (1)
            self.assertEqual(len(executed_tasks), 2)
            self.assertEqual(self.manager.get_task(p3.id)["status"], "queued")

            # Complete p1: active count for provider is now 1 (which meets new limit 1)
            completed_tasks.add(p1.id)
            time.sleep(0.9)
            self.assertEqual(self.manager.get_task(p1.id)["status"], "completed")
            self.assertEqual(len(executed_tasks), 2)
            self.assertEqual(self.manager.get_task(p3.id)["status"], "queued")

            # Complete p2: active count for provider is now 0 (< 1)
            completed_tasks.add(p2.id)
            time.sleep(0.9)
            self.assertEqual(self.manager.get_task(p2.id)["status"], "completed")

            # Now p3 should have started downloading!
            self.assertEqual(len(executed_tasks), 3)
            self.assertIn(p3.id, executed_tasks)
            self.assertEqual(self.manager.get_task(p3.id)["status"], "downloading")

            # Clean up
            completed_tasks.add(p3.id)
            time.sleep(0.2)


if __name__ == "__main__":
    unittest.main()
