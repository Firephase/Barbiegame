"""PDF parsing.

Text is kept page-anchored so every citation carries a real page number a
reader can turn to.  If a PDF yields no extractable text we say so and point
at OCR — we never hand back an empty document as if it were parsed.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from ...core.errors import UnsupportedContent
from ...core.provenance import Author, Passage, Source, SourceKind
from ...core.registry import Provider, ProviderStatus
from ...core.text import chunk, normalise

CAPABILITY = "document_parse"


def parse_pdf_bytes(data: bytes, *, title: str = "Uploaded PDF") -> Source:
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise UnsupportedContent(f"This file could not be read as a PDF: {exc}") from exc

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise UnsupportedContent(
                "This PDF is password protected, so its text cannot be read."
            ) from exc

    meta = reader.metadata or {}
    published = None
    raw_date = str(meta.get("/CreationDate") or "")
    if raw_date.startswith("D:") and len(raw_date) >= 10:
        try:
            published = datetime.strptime(raw_date[2:10], "%Y%m%d").date()
        except ValueError:
            published = None

    src = Source(
        kind=SourceKind.UPLOADED_DOCUMENT,
        title=normalise(str(meta.get("/Title") or "")) or title,
        authors=[Author.parse(a) for a in str(meta.get("/Author") or "").split(";") if a.strip()],
        publisher=normalise(str(meta.get("/Producer") or "")) or None,
        published=published,
        retrieved_by="pypdf",
        full_text_retrieved=True,
        retrieval_note=f"Parsed {len(reader.pages)} page(s) of embedded text.",
        extra={"page_count": len(reader.pages)},
    )

    empty_pages = 0
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            text = normalise(page.extract_text() or "")
        except Exception:
            text = ""
        if not text:
            empty_pages += 1
            continue
        for start, end, part in chunk(text, size=1600, overlap=180):
            src.passages.append(
                Passage(source_id=src.id, text=part, page=page_no,
                        char_start=start, char_end=end)
            )

    src.extra["pages_without_text"] = empty_pages
    if not src.passages:
        src.full_text_retrieved = False
        src.retrieval_note = (
            "No embedded text found — this is most likely a scanned PDF. "
            "Run OCR on it before asking for claims to be grounded in its content."
        )
    elif empty_pages:
        src.retrieval_note += f" {empty_pages} page(s) held no extractable text (likely scans)."
    if src.passages:
        src.abstract = normalise(" ".join(p.text for p in src.passages[:2]))[:1200]
    return src


class PdfParser(Provider):
    capability = CAPABILITY
    name = "pdf"
    requires_credentials = False
    priority = 10
    extensions = (".pdf",)

    def status(self) -> ProviderStatus:
        try:
            import pypdf  # noqa: F401
        except ImportError:
            return ProviderStatus(False, "pypdf is not installed.")
        return ProviderStatus(True, details={"extensions": list(self.extensions)})

    def parse(self, data: bytes, filename: str) -> Source:
        return parse_pdf_bytes(data, title=filename)
