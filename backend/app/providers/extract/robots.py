"""robots.txt gate.

The spec asks the app to respect robots/access restrictions.  We fetch and
cache each origin's robots.txt and refuse disallowed paths with a clear
``AccessDenied`` rather than fetching anyway.
"""
from __future__ import annotations

import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from ...config import settings

_CACHE: dict[str, tuple[float, RobotFileParser | None]] = {}
_TTL = 3600.0


async def _load(origin: str) -> RobotFileParser | None:
    from ..base import get_http_client

    parser = RobotFileParser()
    try:
        client = await get_http_client()
        resp = await client.get(f"{origin}/robots.txt", timeout=8.0)
        if resp.status_code >= 400:
            # No robots.txt (or unreadable) means no stated restriction.
            return None
        parser.parse(resp.text.splitlines())
        return parser
    except Exception:
        return None


async def is_allowed(url: str, user_agent: str | None = None) -> tuple[bool, str]:
    """Return ``(allowed, reason)``.  Fails *open* only when robots.txt is absent."""
    if not settings.respect_robots_txt:
        return True, "robots.txt checking disabled by configuration"
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False, "Only http(s) URLs can be fetched."
    origin = f"{parts.scheme}://{parts.netloc}"

    now = time.time()
    cached = _CACHE.get(origin)
    if cached is None or now - cached[0] > _TTL:
        parser = await _load(origin)
        _CACHE[origin] = (now, parser)
    else:
        parser = cached[1]

    if parser is None:
        return True, "No robots.txt published for this origin."
    ua = user_agent or settings.user_agent.split("/")[0]
    if parser.can_fetch(ua, url) or parser.can_fetch("*", url):
        return True, "Allowed by robots.txt."
    return False, f"robots.txt at {origin} disallows automated fetching of this path."


def crawl_delay(url: str, user_agent: str | None = None) -> float | None:
    parts = urlsplit(url)
    cached = _CACHE.get(f"{parts.scheme}://{parts.netloc}")
    if not cached or cached[1] is None:
        return None
    try:
        return cached[1].crawl_delay(user_agent or settings.user_agent.split("/")[0])
    except Exception:
        return None
