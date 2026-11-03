"""Redacted download diagnostics shared by the engine and compatibility shims."""

import logging
import re
import urllib.parse
from collections.abc import Mapping

logger = logging.getLogger("video_dl.http")


def redact_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.netloc.rsplit("@", 1)[-1]
        return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except ValueError:
        return "<invalid URL>"


def redact_message(message: str) -> str:
    # External downloader command lines may serialize cookies and arbitrary headers.
    if re.search(r"(?:^|\s)-(?:headers|cookies)\b", message):
        return "External downloader command: <HTTP arguments redacted>"
    # yt-dlp also includes query strings in bare extractor IDs, without a URL scheme.
    message = re.sub(r"https?://[^\s<>\"']+", lambda m: redact_url(m.group()), message)
    return re.sub(r"\?[^\s\]\)\"']+", "?<redacted>", message)


def summarize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    visible = {
        "user-agent", "accept", "accept-language", "sec-fetch-mode", "sec-fetch-dest", "sec-fetch-site",
        "server", "content-type", "retry-after",
    }
    result = {}
    for name, value in headers.items():
        key = name.lower()
        if key in {"referer", "origin", "location"}:
            result[name] = redact_url(value)
        elif key in visible:
            result[name] = value
        else:
            result[name] = "<present>" if value else "<empty>"
    return result


class YtdlpLogger:
    def __init__(self, task_id: str, verbose: bool = False):
        self.task_id = task_id
        self.verbose = verbose

    def debug(self, message: str) -> None:
        level = logging.DEBUG if message.startswith("[debug]") and not self.verbose else logging.INFO
        logger.log(level, "Task %s yt-dlp: %s", self.task_id, redact_message(message))

    def warning(self, message: str) -> None:
        logger.warning("Task %s yt-dlp: %s", self.task_id, redact_message(message))

    def error(self, message: str) -> None:
        logger.error("Task %s yt-dlp: %s", self.task_id, redact_message(message))
