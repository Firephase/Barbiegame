"""URL-extraction capability contract."""
from __future__ import annotations

from ...core.provenance import Source
from ..base import HttpProvider

CAPABILITY = "url_extract"


class ExtractorProvider(HttpProvider):
    capability = CAPABILITY
    requires_credentials = False

    def handles(self, url: str) -> bool:
        return url.lower().startswith(("http://", "https://"))

    async def extract(self, url: str) -> Source:  # pragma: no cover
        raise NotImplementedError
