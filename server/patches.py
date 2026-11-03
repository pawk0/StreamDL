import logging
import sys
import urllib.parse
from functools import wraps
from typing import Any, cast

import yt_dlp
import yt_dlp.utils
import yt_dlp.utils._utils
from yt_dlp.networking.common import RequestHandler
from yt_dlp.networking.exceptions import HTTPError

from server.diagnostics import redact_url, summarize_headers

logger = logging.getLogger("video_dl.patches")

UNSAFE_SCRIPT_EXTS = frozenset([
    "php", "asp", "aspx", "jsp", "cgi", "cfm", "pl", "py",
    "html", "htm", "shtml", "action", "do", "js", "css"
])


def apply_ytdlp_patches() -> None:
    """
    Applies compatibility monkey-patches to yt-dlp.

    1. Smart extension detection:
       Addresses false positive '_UnsafeExtensionError: unsafe file extension: php'
       when accessing streaming gateway endpoints (e.g., /remote_control.php?file=xxx.mp4&token=yyy,
       common in KVS and tube CDN architectures).
       Maintains full CVE-2024-38519 / GHSA-79w7-vh3h-8g4j security guarantees:
       files are strictly saved as valid media files (e.g. .mp4), never as executable scripts.

    2. HTTP media headers:
       Treat an empty Accept-Language override as omission after all yt-dlp defaults
       are merged, and report redacted manifest requests and HTTP failures.
    """
    _patch_http_headers()
    orig_determine_ext: Any = getattr(yt_dlp.utils, "_orig_determine_ext", None)
    if orig_determine_ext is None:
        orig_determine_ext = yt_dlp.utils.determine_ext
        yt_dlp.utils._orig_determine_ext = orig_determine_ext  # pyrefly: ignore [missing-attribute] - stashing backup of original function on module

    allowed_exts = getattr(
        yt_dlp.utils._utils._UnsafeExtensionError,
        "ALLOWED_EXTENSIONS",
        frozenset()
    )

    def smart_determine_ext(url: str | None, default_ext: str | None = "unknown_video") -> str | None:
        if not url:
            return default_ext

        ext = orig_determine_ext(url, default_ext=None)

        # If extension is a safe, allowed media extension, use it directly
        if ext and ext.lower() in allowed_exts and ext.lower() not in UNSAFE_SCRIPT_EXTS:
            return ext

        # If extension is a script or unsafe, inspect query parameters for valid media filenames
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.query:
                qs = urllib.parse.parse_qs(parsed.query)
                # Check common media query parameters first
                for param_name in ("file", "filename", "video", "url", "f", "src", "path", "media", "stream"):
                    if param_name in qs:
                        for val in qs[param_name]:
                            val_ext = orig_determine_ext(val, default_ext=None)
                            if val_ext and val_ext.lower() in yt_dlp.utils.KNOWN_EXTENSIONS:
                                return val_ext

                # Check any parameter value ending with a known media extension
                for val_list in qs.values():
                    for val in val_list:
                        val_ext = orig_determine_ext(val, default_ext=None)
                        if val_ext and val_ext.lower() in yt_dlp.utils.KNOWN_EXTENSIONS:
                            return val_ext
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"Failed to inspect query parameters for extension: {e}")

        # Return default_ext (e.g. None so GenericIE falls back to urlhandle_detect_ext / Content-Type)
        return default_ext

    yt_dlp.utils.determine_ext = smart_determine_ext  # pyrefly: ignore [bad-assignment] - patched function returns str | None
    yt_dlp.utils._utils.determine_ext = smart_determine_ext  # pyrefly: ignore [bad-argument-type, bad-assignment] - dynamic patch

    # Update any already-loaded modules that imported determine_ext
    for mod in list(sys.modules.values()):
        if mod and hasattr(mod, "determine_ext"):
            try:
                mod.determine_ext = smart_determine_ext  # pyrefly: ignore [missing-attribute] - dynamically patching already-loaded modules
            except (AttributeError, TypeError) as mod_err:
                logger.debug(f"Could not patch determine_ext on module {getattr(mod, '__name__', mod)}: {mod_err}")


def _patch_http_headers() -> None:
    """Omit empty language headers after yt-dlp merges all request defaults."""
    # Private transport methods are missing from the third-party type stubs.
    handler_type = cast(Any, RequestHandler)
    original = handler_type._get_headers
    if getattr(original, "_video_dl_patched", False):
        return
    original_send = handler_type.send

    @wraps(original)
    def get_headers(self, request):
        headers = original(self, request)
        for name in list(headers):
            if name.lower() == "accept-language" and not headers[name]:
                del headers[name]
        path = urllib.parse.urlsplit(request.url).path.lower()
        prefix = "" if path.endswith((".m3u8", ".mpd")) else "[debug] "
        self._logger.info(
            f"{prefix}[http] {request.method} {redact_url(request.url)} "
            f"via {self.RH_NAME}; headers={summarize_headers(headers)}; "
            f"Accept-Language={'present' if any(k.lower() == 'accept-language' for k in headers) else 'absent'}; "
            f"cookie_jar={'present' if len(self._get_cookiejar(request)) else 'empty'}; "
            f"proxy_schemes={sorted(self._get_proxies(request))}"
        )
        return headers

    @wraps(original_send)
    def send(self, request):
        try:
            response = original_send(self, request)
        except HTTPError as exc:
            response_headers = {
                name: exc.response.headers[name]
                for name in ("Server", "Content-Type", "Location", "Retry-After")
                if name in exc.response.headers
            }
            self._logger.warning(
                f"[http] HTTP {exc.status} {request.method} {redact_url(request.url)} "
                f"via {self.RH_NAME}; response_url={redact_url(exc.response.url)}; "
                f"response_headers={summarize_headers(response_headers)}"
            )
            raise
        if urllib.parse.urlsplit(request.url).path.lower().endswith((".m3u8", ".mpd")):
            self._logger.info(f"[http] HTTP {response.status} {redact_url(response.url)} via {self.RH_NAME}")
        return response

    cast(Any, get_headers)._video_dl_patched = True
    handler_type._get_headers = get_headers
    handler_type.send = send
