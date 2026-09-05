"""Shared plumbing for provider adapters."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..config import settings
from ..core.errors import ProviderFailed
from ..core.registry import Provider, ProviderStatus

__all__ = ["Provider", "ProviderStatus", "HttpProvider", "get_http_client", "close_http_client"]

_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()


async def get_http_client() -> httpx.AsyncClient:
    """One pooled client for the whole process, with a polite UA."""
    global _client
    if _client is None or _client.is_closed:
        async with _lock:
            if _client is None or _client.is_closed:
                _client = httpx.AsyncClient(
                    timeout=httpx.Timeout(settings.http_timeout_seconds),
                    follow_redirects=True,
                    headers={
                        "User-Agent": settings.user_agent,
                        "Accept-Language": "en,*;q=0.5",
                    },
                    limits=httpx.Limits(max_connections=24, max_keepalive_connections=12),
                )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class HttpProvider(Provider):
    """Adapter that talks to an HTTP API, with uniform error translation."""

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        retries: int = 2,
        **kwargs: Any,
    ) -> Any:
        client = await get_http_client()
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = await client.request(method, url, **kwargs)
                if resp.status_code == 429 and attempt < retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                if not resp.content:
                    return None
                ctype = resp.headers.get("content-type", "")
                if "json" in ctype:
                    return resp.json()
                return resp.text
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:300] if exc.response is not None else ""
                raise ProviderFailed(
                    f"{self.name} returned HTTP {exc.response.status_code}.",
                    detail={"provider": self.name, "url": str(url), "body": body},
                ) from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                if attempt < retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
        raise ProviderFailed(
            f"{self.name} was unreachable: {last}",
            detail={"provider": self.name, "url": str(url)},
        )

    async def request_text(self, method: str, url: str, **kwargs: Any) -> str:
        out = await self.request_json(method, url, **kwargs)
        return out if isinstance(out, str) else ""
