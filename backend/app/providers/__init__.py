"""Provider bootstrap.

Every adapter is registered *lazily*: a missing optional dependency or a broken
vendor SDK downgrades one capability instead of preventing the app from
starting.  ``bootstrap()`` is idempotent and is called once on startup and by
the test fixtures.
"""
from __future__ import annotations

from ..core.registry import registry

_BOOTSTRAPPED = False


def bootstrap() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    # -- LLM ---------------------------------------------------------
    def _anthropic():
        from .llm.anthropic_llm import AnthropicLlm

        return AnthropicLlm()

    def _openai():
        from .llm.openai_llm import OpenAiCompatibleLlm

        return OpenAiCompatibleLlm()

    def _extractive():
        from .llm.extractive import ExtractiveLlm

        return ExtractiveLlm()

    registry.register_lazy("llm", "anthropic", _anthropic)
    registry.register_lazy("llm", "openai", _openai)
    registry.register_lazy("llm", "extractive", _extractive)

    # -- web search --------------------------------------------------
    def _tavily():
        from .search.tavily import TavilySearch

        return TavilySearch()

    def _brave():
        from .search.brave import BraveSearch

        return BraveSearch()

    def _serper():
        from .search.serper import SerperSearch

        return SerperSearch()

    def _searxng():
        from .search.searxng import SearxngSearch

        return SearxngSearch()

    def _wikipedia():
        from .search.wikipedia import WikipediaSearch

        return WikipediaSearch()

    def _fixture():
        from .search.fixture import FixtureSearch

        return FixtureSearch()

    registry.register_lazy("web_search", "tavily", _tavily)
    registry.register_lazy("web_search", "brave", _brave)
    registry.register_lazy("web_search", "serper", _serper)
    registry.register_lazy("web_search", "searxng", _searxng)
    registry.register_lazy("web_search", "wikipedia", _wikipedia)
    registry.register_lazy("web_search", "fixture", _fixture)

    # -- academic search ---------------------------------------------
    def _openalex():
        from .academic.openalex import OpenAlexProvider

        return OpenAlexProvider()

    def _crossref():
        from .academic.crossref import CrossrefProvider

        return CrossrefProvider()

    def _arxiv():
        from .academic.arxiv import ArxivProvider

        return ArxivProvider()

    def _europepmc():
        from .academic.europepmc import EuropePMCProvider

        return EuropePMCProvider()

    def _s2():
        from .academic.semanticscholar import SemanticScholarProvider

        return SemanticScholarProvider()

    registry.register_lazy("academic_search", "openalex", _openalex)
    registry.register_lazy("academic_search", "crossref", _crossref)
    registry.register_lazy("academic_search", "arxiv", _arxiv)
    registry.register_lazy("academic_search", "europepmc", _europepmc)
    registry.register_lazy("academic_search", "semanticscholar", _s2)

    # -- extraction / documents / video ------------------------------
    def _http():
        from .extract.http_extractor import HttpExtractor

        return HttpExtractor()

    def _pdf():
        from .documents.pdf import PdfParser

        return PdfParser()

    def _text():
        from .documents.office import TextParser

        return TextParser()

    def _docx():
        from .documents.office import DocxParser

        return DocxParser()

    def _tabular():
        from .documents.office import TabularParser

        return TabularParser()

    def _ocr():
        from .documents.ocr import TesseractOcr

        return TesseractOcr()

    def _youtube():
        from .video.youtube import YouTubeTranscripts

        return YouTubeTranscripts()

    registry.register_lazy("url_extract", "http", _http)
    registry.register_lazy("document_parse", "pdf", _pdf)
    registry.register_lazy("document_parse", "text", _text)
    registry.register_lazy("document_parse", "docx", _docx)
    registry.register_lazy("document_parse", "tabular", _tabular)
    registry.register_lazy("ocr", "tesseract", _ocr)
    registry.register_lazy("video_transcript", "youtube", _youtube)

    # -- infrastructure ----------------------------------------------
    def _index():
        from .index.sqlite_fts import SqliteFtsIndex

        return SqliteFtsIndex()

    def _storage():
        from .storage.local import LocalStorage

        return LocalStorage()

    registry.register_lazy("passage_index", "sqlite_fts", _index)
    registry.register_lazy("blob_storage", "local", _storage)

    _BOOTSTRAPPED = True


CAPABILITIES = (
    "llm",
    "web_search",
    "academic_search",
    "url_extract",
    "document_parse",
    "ocr",
    "video_transcript",
    "passage_index",
    "blob_storage",
)
