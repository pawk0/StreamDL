import logging
import random
import re
import ssl
import string
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from server.config import load_settings, match_provider
from server.utils import is_tls_cert_error, is_valid_http_url

logger = logging.getLogger("video_dl.resolvers")

DEFAULT_RESOLVER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

UrlResolver = Callable[[str, dict[str, str] | None], tuple[str, dict[str, str]] | None]
UrlMatcher = Callable[[str], bool]


def open_url_with_tls_policy(
    req: urllib.request.Request,
    timeout: int = 12,
    tls_mode: str | None = None,
) -> Any:
    """
    Opens a urllib Request respecting the configured tls_mode policy:
      - 'permissive': uses scoped unverified SSL context.
      - 'auto': tries verified SSL context first; if an SSL certificate verification
        error occurs on a domain matching a configured provider, logs a loud warning
        and retries with a scoped unverified SSL context.
      - 'strict': uses verified SSL context with zero fallback.
    Never monkeypatches process-wide SSL contexts.
    """
    if tls_mode is None:
        settings = load_settings()
        tls_mode = str(settings.get("tls_mode", "auto")).lower()

    def _safe_urlopen(r: urllib.request.Request, to: int, ctx: ssl.SSLContext | None) -> Any:
        try:
            if ctx is not None:
                return urllib.request.urlopen(r, timeout=to, context=ctx)
            return urllib.request.urlopen(r, timeout=to)
        except TypeError as te:
            if "context" in str(te):
                return urllib.request.urlopen(r, timeout=to)
            raise

    # 1. Permissive mode: scoped unverified context
    if tls_mode == "permissive":
        ctx = ssl._create_unverified_context()
        return _safe_urlopen(req, timeout, ctx)

    # 2. Auto or Strict mode: try verified context first
    verified_ctx = ssl.create_default_context()
    try:
        return _safe_urlopen(req, timeout, verified_ctx)
    except (urllib.error.URLError, ssl.SSLError, OSError) as e:
        if is_tls_cert_error(e) and tls_mode == "auto":
            req_url = req.full_url if hasattr(req, "full_url") else str(req)
            settings = load_settings()
            pid, pname, _ = match_provider(req_url, settings=settings)
            known_pids = {p.get("id") for p in settings.get("providers", []) if isinstance(p, dict)}
            if pid in known_pids:
                logger.warning(
                    f"TLS certificate verification failed for {req_url} ({e}); "
                    f"falling back to unverified TLS for matched provider '{pname}' rotating domain."
                )
                unverified_ctx = ssl._create_unverified_context()
                return _safe_urlopen(req, timeout, unverified_ctx)
        raise


def is_doodstream_url(url: str | None, settings: dict | None = None) -> bool:
    """Checks whether the URL belongs to Doodstream based on configured provider patterns."""
    if not url or not isinstance(url, str):
        return False
    provider_id, _, _ = match_provider(url, settings=settings)
    return provider_id == "doodstream"


def is_doodstream_embed_url(url: str | None, settings: dict | None = None) -> bool:
    """
    Checks whether a URL is a Doodstream page/embed URL requiring stream resolution.
    Direct stream URLs (containing /pass_md5/ or query parameters) do not require resolution.
    """
    if not url or not is_doodstream_url(url, settings=settings):
        return False
    return "/pass_md5/" not in url and "?" not in url


def resolve_doodstream(
    url: str,
    custom_headers: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]] | None:
    """
    Resolves a Doodstream page/embed URL (e.g. /e/xxx or /d/xxx) into the direct streaming media URL.
    Returns (direct_stream_url, headers_dict) or None if resolution fails.
    """
    if not is_valid_http_url(url):
        logger.warning(f"Doodstream resolver received invalid embed URL: '{url}'")
        return None

    try:
        # Convert /d/ (download) to /e/ (embed)
        embed_url = re.sub(r'/(d)/', '/e/', url)
        parsed_embed = urllib.parse.urlparse(embed_url)
        scheme = parsed_embed.scheme.lower() if parsed_embed.scheme else "https"
        domain = parsed_embed.netloc
        base_domain = f"{scheme}://{domain}"

        # Extract or default User-Agent with case-insensitivity
        user_agent = DEFAULT_RESOLVER_USER_AGENT
        if custom_headers:
            for k, v in custom_headers.items():
                if k.lower() == "user-agent" and v:
                    user_agent = v
                    break

        headers: dict[str, str] = {
            "User-Agent": user_agent,
            "Referer": embed_url,
        }
        if custom_headers:
            for k, v in custom_headers.items():
                if k.lower() not in ("referer", "host") and v:
                    headers[k] = v

        # 1. Fetch embed page HTML
        req = urllib.request.Request(embed_url, headers=headers)
        try:
            with open_url_with_tls_policy(req, timeout=12) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
        except urllib.error.HTTPError as e:
            logger.warning(f"Doodstream HTTP {e.code} ({e.reason}) fetching embed {embed_url} for {url}")
            return None
        except urllib.error.URLError as e:
            logger.warning(f"Doodstream network error fetching embed {embed_url} for {url}: {e.reason}")
            return None
        except TimeoutError:
            logger.warning(f"Doodstream timeout fetching embed {embed_url} for {url}")
            return None
        except OSError as e:
            logger.warning(f"Doodstream OS/socket error fetching embed {embed_url} for {url}: {e}")
            return None

        # 2. Find pass_md5 path: /pass_md5/...
        pass_match = re.search(r"(/pass_md5/[a-zA-Z0-9_\-]+)", html)
        if not pass_match:
            pass_match = re.search(r"\$\.get\('(/pass_md5/[^']+)'", html)
        if not pass_match:
            logger.warning(f"Doodstream resolver failed to find pass_md5 path in embed HTML for {url}")
            return None

        pass_path = pass_match.group(1)
        pass_url = f"{base_domain}{pass_path}"
        if not is_valid_http_url(pass_url):
            logger.warning(f"Doodstream resolver derived invalid pass_url '{pass_url}' for {url}")
            return None

        # 3. Fetch pass_url to get base stream URL prefix
        pass_req = urllib.request.Request(pass_url, headers=headers)
        try:
            with open_url_with_tls_policy(pass_req, timeout=12) as resp:
                stream_base = resp.read().decode('utf-8', errors='ignore').strip()
        except urllib.error.HTTPError as e:
            logger.warning(f"Doodstream HTTP {e.code} ({e.reason}) fetching pass URL {pass_url} for {url}")
            return None
        except urllib.error.URLError as e:
            logger.warning(f"Doodstream network error fetching pass URL {pass_url} for {url}: {e.reason}")
            return None
        except TimeoutError:
            logger.warning(f"Doodstream timeout fetching pass URL {pass_url} for {url}")
            return None
        except OSError as e:
            logger.warning(f"Doodstream OS/socket error fetching pass URL {pass_url} for {url}: {e}")
            return None

        # 4. Validate stream_base scheme (SSRF prevention)
        if not is_valid_http_url(stream_base):
            logger.warning(
                f"Doodstream resolver received invalid stream base URI '{stream_base[:100]}' for {url}"
            )
            return None

        # 5. Extract token from JS
        token_match = re.search(r"token=['\"]?([a-zA-Z0-9]+)", html)
        token = token_match.group(1) if token_match else "undefined"

        # 6. Generate random 10 characters as required by Doodstream player
        rand_chars = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        expiry = int(time.time() * 1000)

        direct_url = f"{stream_base}{rand_chars}?token={token}&expiry={expiry}"
        if not is_valid_http_url(direct_url):
            logger.warning(
                f"Doodstream resolver constructed invalid direct stream URL '{direct_url[:100]}' for {url}"
            )
            return None

        # 7. Construct stream headers
        stream_headers: dict[str, str] = {
            "User-Agent": user_agent,
            "Referer": f"{base_domain}/",
        }
        if custom_headers:
            for k, v in custom_headers.items():
                if k.lower() not in ("referer", "host") and v:
                    stream_headers[k] = v

        logger.info(f"Resolved Doodstream embed URL to direct stream: {direct_url[:50]}...")
        return direct_url, stream_headers

    except (ValueError, IndexError, UnicodeDecodeError) as e:
        logger.warning(f"Doodstream resolver exception for {url}: {e}")
        return None


class StreamResolver:
    """Represents a registered stream resolver with URL matching and resolution logic."""

    def __init__(
        self,
        name: str,
        matcher: UrlMatcher,
        resolver: UrlResolver,
        priority: int = 100,
    ) -> None:
        self.name = name
        self.matcher = matcher
        self.resolver = resolver
        self.priority = priority

    def can_resolve(self, url: str) -> bool:
        try:
            return bool(self.matcher(url))
        except Exception as e:  # noqa: BLE001 - third-party resolver matcher plugins may raise arbitrary exceptions
            logger.debug(f"Resolver matcher error for '{self.name}' on {url}: {e}")
            return False

    def resolve(
        self, url: str, custom_headers: dict[str, str] | None = None
    ) -> tuple[str, dict[str, str]] | None:
        return self.resolver(url, custom_headers)


class ResolverRegistry:
    """Thread-safe registry of stream resolvers matching and resolving host embeds to direct streams."""

    def __init__(self) -> None:
        self._resolvers: list[StreamResolver] = []
        self._lock = threading.RLock()
        self._init_defaults()

    def _init_defaults(self) -> None:
        self.register(
            name="doodstream",
            matcher=is_doodstream_embed_url,
            resolver=lambda url, headers=None: resolve_doodstream(url, headers),
            priority=100,
        )

    def register(
        self,
        name: str,
        matcher: UrlMatcher,
        resolver: UrlResolver,
        priority: int = 100,
    ) -> None:
        with self._lock:
            self._resolvers = [r for r in self._resolvers if r.name != name]
            self._resolvers.append(StreamResolver(name, matcher, resolver, priority))
            self._resolvers.sort(key=lambda r: r.priority, reverse=True)

    def unregister(self, name: str) -> bool:
        with self._lock:
            orig_len = len(self._resolvers)
            self._resolvers = [r for r in self._resolvers if r.name != name]
            return len(self._resolvers) < orig_len

    def get(self, name: str) -> StreamResolver | None:
        with self._lock:
            for r in self._resolvers:
                if r.name == name:
                    return r
        return None

    def find_resolver(self, url: str) -> StreamResolver | None:
        with self._lock:
            resolvers = list(self._resolvers)
        for r in resolvers:
            if r.can_resolve(url):
                return r
        return None

    def resolve(
        self, url: str, custom_headers: dict[str, str] | None = None
    ) -> tuple[str, dict[str, str]] | None:
        with self._lock:
            resolvers = list(self._resolvers)
        for r in resolvers:
            if r.can_resolve(url):
                try:
                    res = r.resolve(url, custom_headers)
                    if res is not None:
                        return res
                except Exception as e:  # noqa: BLE001 - third-party resolver plugins may raise arbitrary exceptions during resolution
                    logger.warning(f"Resolver '{r.name}' error resolving {url}: {e}")
        return None

    def clear(self) -> None:
        with self._lock:
            self._resolvers.clear()

    def reset(self) -> None:
        with self._lock:
            self._resolvers.clear()
            self._init_defaults()


default_resolver_registry = ResolverRegistry()


def register_resolver(
    name: str,
    matcher: UrlMatcher,
    resolver: UrlResolver,
    priority: int = 100,
) -> None:
    default_resolver_registry.register(name, matcher, resolver, priority)


def unregister_resolver(name: str) -> bool:
    return default_resolver_registry.unregister(name)


def resolve_url(
    url: str,
    custom_headers: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]] | None:
    return default_resolver_registry.resolve(url, custom_headers)
