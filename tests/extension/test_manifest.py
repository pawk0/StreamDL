import json
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parent.parent.parent / "extension"
MANIFEST_PATH = EXTENSION_DIR / "manifest.json"


def test_manifest_file_exists_and_valid_json():
    assert MANIFEST_PATH.exists(), f"Manifest not found at {MANIFEST_PATH}"
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_manifest_v3_structure():
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert data.get("manifest_version") == 3
    assert data.get("name") == "StreamDL - Video Downloader Companion"
    assert data.get("version") is not None


def test_manifest_permissions():
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    permissions = set(data.get("permissions", []))
    required_permissions = {
        "webRequest",
        "storage",
        "contextMenus",
        "activeTab",
        "tabs",
        "notifications",
    }
    assert required_permissions.issubset(permissions)


def test_manifest_host_permissions():
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    host_permissions = data.get("host_permissions", [])
    assert "<all_urls>" in host_permissions
    assert "http://localhost:7921/*" in host_permissions
    assert "http://127.0.0.1:7921/*" in host_permissions


def test_manifest_service_worker_exists():
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    sw_rel = data.get("background", {}).get("service_worker")
    assert sw_rel == "background.js"
    sw_path = EXTENSION_DIR / sw_rel
    assert sw_path.exists(), f"Service worker not found: {sw_path}"

    sw_content = sw_path.read_text(encoding="utf-8")
    assert 'importScripts("utils.js")' in sw_content


def test_manifest_action_and_popup_exists():
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    popup_rel = data.get("action", {}).get("default_popup")
    assert popup_rel == "popup/popup.html"
    popup_path = EXTENSION_DIR / popup_rel
    assert popup_path.exists(), f"Popup HTML not found: {popup_path}"

    popup_content = popup_path.read_text(encoding="utf-8")
    assert '<script src="../utils.js"></script>' in popup_content
    assert '<script src="popup.js"></script>' in popup_content


def test_manifest_content_scripts_exist():
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    content_scripts = data.get("content_scripts", [])
    assert len(content_scripts) > 0
    for cs in content_scripts:
        assert "<all_urls>" in cs.get("matches", [])
        for js_file in cs.get("js", []):
            cs_path = EXTENSION_DIR / js_file
            assert cs_path.exists(), f"Content script not found: {cs_path}"


def test_manifest_icons_exist():
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    icons = data.get("icons", {})
    for size, icon_rel in icons.items():
        icon_path = EXTENSION_DIR / icon_rel
        assert icon_path.exists(), f"Icon {size} not found: {icon_path}"


def test_utils_file_exists():
    utils_path = EXTENSION_DIR / "utils.js"
    assert utils_path.exists(), f"utils.js not found: {utils_path}"
    content = utils_path.read_text(encoding="utf-8")
    assert "function getServerUrl" in content
    assert "function analyzeStreamUrl" in content
    assert "function extractHeaders" in content
    assert "function deriveOriginFromReferer" in content
    assert "function matchPattern" in content
    assert "function detectProvider" in content
