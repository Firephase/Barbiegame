"""Shared API helpers."""
from __future__ import annotations

from typing import Any

from fastapi import UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..core.errors import BadRequest, NotFound, ProviderUnavailable, UnsupportedContent
from ..core.provenance import Source
from ..core.registry import registry
from ..models import SourceRecord


async def read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise BadRequest(f"'{file.filename}' is empty.")
    if len(data) > settings.max_upload_bytes:
        raise BadRequest(
            f"'{file.filename}' is {len(data) / 1e6:.1f} MB, over the "
            f"{settings.max_upload_bytes / 1e6:.0f} MB per-file limit."
        )
    return data


def parser_for(filename: str):
    """Pick the document parser registered for this extension."""
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    for provider in registry.all("document_parse"):
        if suffix in getattr(provider, "extensions", ()) and provider.available:
            return provider
    known = sorted(
        {ext for p in registry.all("document_parse") for ext in getattr(p, "extensions", ())}
    )
    raise UnsupportedContent(
        f"No parser is configured for '{suffix or filename}'. Supported: {', '.join(known)}.",
        detail={"supported": known},
    )


def storage():
    return registry.require("blob_storage", settings.storage_provider)


def load_source(session: Session, source_id: str, project_id: str | None = None) -> Source:
    record = session.get(SourceRecord, source_id)
    if record is None or (project_id and record.project_id != project_id):
        raise NotFound(f"Source '{source_id}' was not found.")
    return Source.model_validate(record.payload)


def load_source_record(session: Session, source_id: str) -> SourceRecord:
    record = session.get(SourceRecord, source_id)
    if record is None:
        raise NotFound(f"Source '{source_id}' was not found.")
    return record


def frame_from_request(session: Session, *, source_id: str | None, rows: list[dict] | None):
    """Load a dataset either from an uploaded source or from inline rows."""
    import pandas as pd

    from ..services.analysis import frame_from_records, load_frame

    if rows:
        return frame_from_records(rows), "inline data"
    if not source_id:
        raise BadRequest("Provide either 'source_id' (an uploaded dataset) or 'rows'.")
    record = load_source_record(session, source_id)
    if not record.blob_key:
        raise BadRequest(
            f"'{record.title}' has no stored file, so it cannot be analysed as a dataset."
        )
    data = storage().read(record.blob_key)
    return load_frame(data, record.title), record.title


def llm_available() -> bool:
    providers = registry.resolve("llm", settings.llm_provider)
    return bool(providers) and not getattr(providers[0], "is_extractive", False)


def require_reasoning_model(feature: str) -> None:
    if not llm_available():
        raise ProviderUnavailable(
            f"{feature} needs a reasoning model. Set ANTHROPIC_API_KEY or OPENAI_API_KEY "
            f"in your .env and restart. Search, retrieval, citations, statistics and "
            f"charts all work without one.",
            detail={"feature": feature},
        )


def paginate(items: list[Any], limit: int, offset: int) -> dict:
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "limit": limit,
        "offset": offset,
    }
