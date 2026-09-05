"""Academic-literature capability contract."""
from __future__ import annotations

from dataclasses import dataclass, field

from ...core.provenance import Source
from ..base import HttpProvider

CAPABILITY = "academic_search"


@dataclass(slots=True)
class ScholarRequest:
    query: str
    limit: int = 10
    year_from: int | None = None
    year_to: int | None = None
    open_access_only: bool = False
    include_preprints: bool = True
    fields: list[str] = field(default_factory=list)


class AcademicProvider(HttpProvider):
    capability = CAPABILITY
    requires_credentials = False

    async def search(self, request: ScholarRequest) -> list[Source]:  # pragma: no cover
        raise NotImplementedError

    async def lookup_doi(self, doi: str) -> Source | None:
        return None
