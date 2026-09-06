import os
import re
from html.parser import HTMLParser


class ButtonAttrParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.buttons: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "button":
            attr_dict = {k: v for k, v in attrs if v is not None}
            self.buttons.append(attr_dict)


def test_dashboard_buttons_have_aria_labels(client):
    """Ensure key icon and action buttons in index.html have aria-label attributes."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    parser = ButtonAttrParser()
    parser.feed(html)

    buttons_by_id = {b["id"]: b for b in parser.buttons if "id" in b}

    assert "btn-open-settings" in buttons_by_id
    assert buttons_by_id["btn-open-settings"].get("aria-label") == "Settings"

    assert "btn-open-folder" in buttons_by_id
    assert buttons_by_id["btn-open-folder"].get("aria-label") == "Open Downloads Directory"

    assert "btn-clear-completed" in buttons_by_id
    assert buttons_by_id["btn-clear-completed"].get("aria-label") == "Clear completed and failed tasks"

    assert "btn-close-settings" in buttons_by_id
    assert buttons_by_id["btn-close-settings"].get("aria-label") == "Close Settings"

    assert "btn-close-map-provider" in buttons_by_id
    assert buttons_by_id["btn-close-map-provider"].get("aria-label") == "Close Map Provider"


def test_extension_popup_buttons_have_aria_labels():
    """Ensure icon buttons in extension/popup/popup.html have aria-label attributes."""
    popup_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../extension/popup/popup.html"))
    assert os.path.exists(popup_path), f"File not found: {popup_path}"

    with open(popup_path, encoding="utf-8") as f:
        html = f.read()

    parser = ButtonAttrParser()
    parser.feed(html)

    buttons_by_id = {b["id"]: b for b in parser.buttons if "id" in b}
    assert "btn-copy-url" in buttons_by_id
    assert buttons_by_id["btn-copy-url"].get("aria-label") == "Copy stream URL"


def test_app_js_dynamic_buttons_have_aria_labels():
    """Ensure dynamically generated buttons in server/static/js/app.js have aria-label attributes."""
    js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../server/static/js/app.js"))
    assert os.path.exists(js_path), f"File not found: {js_path}"

    with open(js_path, encoding="utf-8") as f:
        js_content = f.read()

    # Verify btn-remove-provider has aria-label
    assert re.search(r'class="btn-remove-provider"[^>]*aria-label="Delete Provider"', js_content)

    # Verify btn-cancel has aria-label
    assert re.search(r'class="[^"]*btn-cancel[^"]*"[^>]*aria-label="Cancel download"', js_content)

    # Verify btn-open-file has aria-label
    assert re.search(r'class="[^"]*btn-open-file[^"]*"[^>]*aria-label="Open Video File"', js_content)
