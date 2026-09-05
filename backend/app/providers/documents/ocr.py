"""OCR for scanned pages and photographed notes.

Optional: enabled only when Tesseract is actually installed.  When it is not,
the provider reports why instead of silently returning empty text, so a scanned
PDF is never mistaken for an empty one.
"""
from __future__ import annotations

import shutil
from io import BytesIO

from ...core.errors import ProviderUnavailable
from ...core.provenance import Passage, Source, SourceKind
from ...core.registry import Provider, ProviderStatus
from ...core.text import chunk, normalise

CAPABILITY = "ocr"


class TesseractOcr(Provider):
    capability = CAPABILITY
    name = "tesseract"
    requires_credentials = False
    priority = 10

    def status(self) -> ProviderStatus:
        if shutil.which("tesseract") is None:
            return ProviderStatus(
                False,
                "Tesseract is not installed. Install the 'tesseract-ocr' package "
                "and 'pytesseract' to read scanned documents.",
            )
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return ProviderStatus(False, "pytesseract is not installed.")
        return ProviderStatus(True, details={"engine": "tesseract"})

    def image_to_text(self, data: bytes, *, lang: str = "eng") -> str:
        st = self.status()
        if not st.available:
            raise ProviderUnavailable(st.reason)
        import pytesseract
        from PIL import Image

        return normalise(pytesseract.image_to_string(Image.open(BytesIO(data)), lang=lang))

    def parse(self, data: bytes, filename: str, *, lang: str = "eng") -> Source:
        text = self.image_to_text(data, lang=lang)
        src = Source(
            kind=SourceKind.UPLOADED_DOCUMENT,
            title=filename,
            retrieved_by=self.name,
            full_text_retrieved=bool(text),
            retrieval_note=(
                "Text recovered by OCR — transcription errors are possible, so quotes "
                "from this source should be checked against the original."
                if text
                else "OCR found no readable text in this image."
            ),
            abstract=text[:800] or None,
        )
        for start, end, part in chunk(text):
            src.passages.append(
                Passage(source_id=src.id, text=part, char_start=start, char_end=end)
            )
        return src
