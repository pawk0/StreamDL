import re


def format_bytes(b: float | None) -> str:
    """Formats a byte value into human-readable representation (B, KB, MB, GB, TB, PB)."""
    if not b or b <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PB"


def format_eta(seconds: int | None) -> str:
    """Formats remaining seconds into mm:ss or hh:mm:ss format."""
    if seconds is None or seconds < 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def sanitize_filename(title: str, max_length: int = 150) -> str:
    """Removes invalid characters for Windows and Unix filesystems, and truncates length."""
    if not title:
        return "video"
    # Remove Windows illegal characters: < > : " / \ | ? *
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip('. ')
    if not cleaned:
        return "video"
    return cleaned[:max_length].strip('. ')


def is_generic_title(title: str | None) -> bool:
    """Checks whether the given title is generic or an uninformative placeholder."""
    if not title:
        return True
    t = title.strip().lower()
    if not t:
        return True
    base = t.rsplit(".", 1)[0] if "." in t else t
    generic_names = {
        "master", "index", "manifest", "playlist", "stream",
        "video", "fetching info...", "undefined", "unknown", "null",
        "remote_control", "remote control", "download", "player"
    }
    return t in generic_names or base in generic_names or t.startswith("index-f") or t.startswith("master-")
