import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.config import match_provider, load_settings, save_settings
from server.downloader import DownloadManager


class TestProviders(unittest.TestCase):
    def setUp(self):
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
        self.settings = load_settings()

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

    def test_doodstream_patterns(self):
        pid, pname, limit = match_provider("https://dood.re/e/abcdef12345")
        self.assertEqual(pid, "doodstream")
        self.assertEqual(pname, "Doodstream")
        self.assertEqual(limit, 1)

        # CDN subdomain
        pid, pname, _ = match_provider("https://dw572mm.cloudatacdn.com/u/token123/stream.mp4")
        self.assertEqual(pid, "doodstream")
        self.assertEqual(pname, "Doodstream")

    def test_elliotintel_patterns(self):
        # Sprintcdn / r66nv9ed.com pattern
        pid, pname, _ = match_provider("https://edge2-waw-sprintcdn.r66nv9ed.com/hls/master.m3u8")
        self.assertEqual(pid, "elliotintel")
        self.assertEqual(pname, "ElliotIntel")

    def test_referer_matching(self):
        # Stream URL is generic/cdn-like, but embed referer points to doodstream
        pid, pname, _ = match_provider(
            url="https://192.168.1.100:8443/video.ts",
            referer="https://dood.video/e/sample"
        )
        self.assertEqual(pid, "doodstream")
        self.assertEqual(pname, "Doodstream")

    def test_unrecognized_domain_fallback(self):
        pid, pname, limit = match_provider("https://sub.cdn.vidsource.org/stream.m3u8")
        self.assertEqual(pid, "vidsource.org")
        self.assertEqual(pname, "vidsource.org")
        self.assertEqual(limit, 1)

    def test_dynamic_custom_provider(self):
        # Add a newly rotating domain to settings
        providers = list(self.settings.get("providers", []))
        providers.append({
            "id": "newhost",
            "name": "NewHost",
            "patterns": ["*rotating-cdn-123.com*"],
            "max_concurrent": 2
        })
        save_settings({"providers": providers})

        pid, pname, limit = match_provider("https://node1.rotating-cdn-123.com/file.mp4")
        self.assertEqual(pid, "newhost")
        self.assertEqual(pname, "NewHost")
        self.assertEqual(limit, 2)

    def test_task_dict_includes_provider(self):
        manager = DownloadManager.get_instance()
        task = manager.add_task(
            url="https://r1148gsx.cloudatacdn.com/u/xyz/video.mp4",
            title="My Test Video"
        )
        data = task.to_dict()
        self.assertEqual(data["provider"], "Doodstream")
        self.assertEqual(data["provider_id"], "doodstream")
        self.assertEqual(data["provider_limit"], 1)


if __name__ == "__main__":
    unittest.main()
