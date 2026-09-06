import os
import re
import ssl
import urllib.error
import urllib.parse


def format_bytes(b: float | None) -> str:
    """Formats a byte value into human-readable representation (B, KB, MB, GB, TB, PB)."""
    if not b or b <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PB"


def format_eta(seconds: float | None) -> str:
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
    if not t or not re.search(r'[\w]', t):
        return True
    base = t.rsplit(".", 1)[0] if "." in t else t
    generic_names = {
        "master", "index", "manifest", "playlist", "stream",
        "video", "fetching info...", "fetching info", "undefined", "unknown", "null",
        "remote_control", "remote control", "download", "player"
    }
    return t in generic_names or base in generic_names or t.startswith(("index-f", "master-"))


def normalize_url(url: str) -> str:
    """Normalizes a URL for comparison: lowercases scheme and host, strips trailing slash from path."""
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urllib.parse.urlunparse((scheme, netloc, path, parsed.params, parsed.query, parsed.fragment))


def get_unique_base(
    download_dir: str | None,
    base_name: str,
    reserved_names: set[str] | None = None,
    max_length: int = 150,
) -> str:
    """
    Computes a collision-free base name using sanitize_filename.
    Checks against:
      1. Case-insensitive in-memory reserved names (from other active/queued tasks).
      2. Files and intermediate format streams in download_dir (case-insensitively).
    Guarantees the output length does not exceed max_length (preserving the counter suffix).
    Treats base_name as immutable, appending ' (1)', ' (2)', etc. upon collision without mutating title numbers.
    """
    clean_base = sanitize_filename(base_name, max_length=max_length)
    reserved_set = {r.lower() for r in reserved_names} if reserved_names else set()

    disk_entries: set[str] = set()
    if download_dir and os.path.exists(download_dir):
        try:
            disk_entries = {f.lower() for f in os.listdir(download_dir)}
        except OSError:
            disk_entries = set()

    def conflicts(candidate: str) -> bool:
        c_lower = candidate.lower()
        if c_lower in reserved_set:
            return True
        for f_lower in disk_entries:
            if f_lower == c_lower:
                return True
            # Strip fragment suffixes like -Frag0.part or .part-Frag0.part
            base_f = re.sub(r"-frag\d+.*$", "", f_lower, flags=re.IGNORECASE)
            while base_f.endswith((".part", ".ytdl", ".temp")):
                base_f = os.path.splitext(base_f)[0]
            stem, _ = os.path.splitext(base_f)
            if stem == c_lower:
                return True
            if bool(re.search(r"^" + re.escape(c_lower) + r"\.f(\d+|ba|bv|hls|dash|[0-9]+p)[a-zA-Z0-9_-]*$", stem)):
                return True
        return False

    if not conflicts(clean_base):
        return clean_base

    counter = 1
    while True:
        suffix = f" ({counter})"
        max_stem = max_length - len(suffix)
        trimmed_stem = clean_base[:max_stem].rstrip('. ')
        candidate = f"{trimmed_stem}{suffix}"
        if not conflicts(candidate):
            return candidate
        counter += 1


def is_valid_http_url(url: str | None) -> bool:
    """Validates that a URL is a non-empty string with an http or https scheme and network host."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc)
    except (ValueError, AttributeError):
        return False


def is_domain_or_subdomain(hostname: str | None, domain: str) -> bool:
    """
    Checks if a hostname exactly matches a domain or is a valid subdomain of it.
    Prevents suffix injection attacks (e.g. evil-doodstream.com.attacker.net).
    """
    if not hostname or not domain:
        return False
    h = hostname.lower().strip()
    d = domain.lower().strip().lstrip(".").rstrip(".")
    if not h or not d:
        return False
    return h == d or h.endswith("." + d)


def is_tls_cert_error(err: BaseException | None) -> bool:
    """Checks whether an exception represents an SSL/TLS certificate verification failure."""
    if err is None:
        return False
    if isinstance(err, ssl.SSLCertVerificationError):
        return True
    if isinstance(err, urllib.error.URLError):
        if isinstance(err.reason, BaseException) and is_tls_cert_error(err.reason):
            return True
        reason_str = str(err.reason).lower()
        if any(msg in reason_str for msg in ("certificate verify failed", "certificate_verify_failed", "self signed", "self-signed", "expired", "ssl: certificate", "hostname mismatch")):
            return True
    if isinstance(err, ssl.SSLError):
        err_str = str(err).lower()
        if any(msg in err_str for msg in ("certificate verify failed", "certificate_verify_failed", "self signed", "self-signed", "expired", "certificateverifyerror", "certificate")):
            return True
    err_str = str(err).lower()
    return any(msg in err_str for msg in ("certificate verify failed", "certificate_verify_failed", "ssl: certificate", "certificateverifyerror"))

