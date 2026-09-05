import logging
import random
import re
import string
import time
import urllib.parse
import urllib.request

logger = logging.getLogger("video_dl.resolvers")


def is_doodstream_url(url: str) -> bool:
    """Checks whether the URL belongs to known Doodstream domains."""
    if not url:
        return False
    lower = url.lower()
    return any(domain in lower for domain in [
        "dood.re", "dood.to", "dood.so", "dood.ws", "dood.cx",
        "dood.sh", "dood.la", "dood.watch", "doodstream.com", "dood.video", "dood.pm", "dood.wf"
    ])


def resolve_doodstream(url: str, custom_headers: dict = None) -> tuple[str, dict] | None:
    """
    Resolves a Doodstream page/embed URL (e.g. /e/xxx or /d/xxx) into the direct streaming media URL.
    Returns (direct_stream_url, headers_dict) or None if failed.
    """
    try:
        # Convert /d/ (download) to /e/ (embed)
        embed_url = re.sub(r'/(d)/', '/e/', url)
        domain = urllib.parse.urlparse(embed_url).netloc
        base_domain = f"https://{domain}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": embed_url
        }
        if custom_headers:
            headers.update(custom_headers)

        req = urllib.request.Request(embed_url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        # Find pass_md5 path: /pass_md5/...
        pass_match = re.search(r"(/pass_md5/[a-zA-Z0-9_\-]+)", html)
        if not pass_match:
            pass_match = re.search(r"\$\.get\('(/pass_md5/[^']+)'", html)
        if not pass_match:
            return None

        pass_path = pass_match.group(1)
        pass_url = f"{base_domain}{pass_path}"

        # Fetch pass_url to get base stream URL prefix
        pass_req = urllib.request.Request(pass_url, headers=headers)
        with urllib.request.urlopen(pass_req, timeout=12) as resp:
            stream_base = resp.read().decode('utf-8', errors='ignore').strip()

        # Find token from JS
        token_match = re.search(r"token=['\"]?([a-zA-Z0-9]+)", html)
        token = token_match.group(1) if token_match else "undefined"

        # Generate random 10 characters as required by Doodstream player
        rand_chars = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        expiry = int(time.time() * 1000)

        direct_url = f"{stream_base}{rand_chars}?token={token}&expiry={expiry}"
        stream_headers = {
            "User-Agent": headers["User-Agent"],
            "Referer": base_domain + "/"
        }
        if custom_headers:
            stream_headers.update(custom_headers)
        logger.info(f"Resolved Doodstream embed URL to direct stream: {direct_url[:50]}...")
        return direct_url, stream_headers
    except Exception as e:
        logger.warning(f"Doodstream resolver exception for {url}: {e}")
        return None
