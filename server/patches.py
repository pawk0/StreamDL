import logging
import sys
import urllib.parse

import yt_dlp
import yt_dlp.utils
import yt_dlp.utils._utils

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
    """
    orig_determine_ext = getattr(yt_dlp.utils, "_orig_determine_ext", None)
    if orig_determine_ext is None:
        orig_determine_ext = yt_dlp.utils.determine_ext
        yt_dlp.utils._orig_determine_ext = orig_determine_ext

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
        except Exception:
            pass

        # Return default_ext (e.g. None so GenericIE falls back to urlhandle_detect_ext / Content-Type)
        return default_ext

    yt_dlp.utils.determine_ext = smart_determine_ext
    yt_dlp.utils._utils.determine_ext = smart_determine_ext

    # Update any already-loaded modules that imported determine_ext
    for mod in list(sys.modules.values()):
        if mod and hasattr(mod, "determine_ext"):
            try:
                mod.determine_ext = smart_determine_ext
            except Exception:
                pass


# Alias for backwards compatibility
patch_ytdlp_extension_handling = apply_ytdlp_patches
