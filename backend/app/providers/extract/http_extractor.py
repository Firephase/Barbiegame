"""Generic web-page reader.

Fetches a URL (robots-permitting), strips chrome, and returns a Source whose
passages are the article's real text plus any tables it found.  Metadata is
lifted from Highwire/Dublin Core/OpenGraph/JSON-LD tags, which is how we get
authors, DOIs and dates off publisher pages without guessing.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from ...config import settings
from ...core.errors import AccessDenied, ProviderFailed, UnsupportedContent
from ...core.provenance import Author, Evidentiary, Passage, Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import chunk, normalise
from ..base import get_http_client
from .base import ExtractorProvider
from .robots import is_allowed

_DROP = ("script", "style", "nav", "footer", "aside", "form", "noscript", "svg",
         "iframe", "button", "template")
_MAIN_HINTS = ("article", "main", '[role="main"]', "#content", ".article-body",
               ".post-content", ".entry-content", "#mw-content-text")

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
_GOV_TLDS = (".gov", ".mil", ".gov.uk", ".europa.eu", ".who.int", ".un.org")
_EDU_TLDS = (".edu", ".ac.uk", ".edu.au", ".ac.jp")


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%B %d, %Y", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y"):
        try:
            return datetime.strptime(raw[: len(datetime.now().strftime(fmt)) + 6][: 30], fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.fullmatch(r"\s*(\d{4})\s*", raw)
    return date(int(m[1]), 1, 1) if m else None


class HttpExtractor(ExtractorProvider):
    name = "http"
    priority = 10

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            True,
            details={
                "respects_robots_txt": settings.respect_robots_txt,
                "max_bytes": settings.max_fetch_bytes,
            },
        )

    # -- metadata helpers ---------------------------------------------
    @staticmethod
    def _metas(soup: BeautifulSoup, *names: str) -> list[str]:
        out: list[str] = []
        for name in names:
            for tag in soup.find_all("meta"):
                key = (tag.get("name") or tag.get("property") or tag.get("itemprop") or "").lower()
                if key == name.lower() and tag.get("content"):
                    out.append(normalise(tag["content"]))
        return out

    @staticmethod
    def _json_ld(soup: BeautifulSoup) -> list[dict]:
        blocks: list[dict] = []
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                payload = json.loads(tag.string or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            blocks.extend(payload if isinstance(payload, list) else [payload])
        return [b for b in blocks if isinstance(b, dict)]

    def _classify(self, source: Source, soup: BeautifulSoup) -> None:
        domain = source.domain or ""
        if domain.endswith(_GOV_TLDS) or any(t in domain for t in _GOV_TLDS):
            source.kind = SourceKind.GOVERNMENT
            source.evidentiary = Evidentiary.SECONDARY
        elif domain.endswith(_EDU_TLDS) or any(t in domain for t in _EDU_TLDS):
            source.kind = SourceKind.INSTITUTIONAL
        elif source.doi:
            source.kind = SourceKind.JOURNAL_ARTICLE
            source.evidentiary = Evidentiary.PRIMARY
        elif self._metas(soup, "article:published_time") or soup.find("time"):
            source.kind = SourceKind.NEWS
            source.evidentiary = Evidentiary.SECONDARY
        elif re.search(r"docs?\.|/documentation|readthedocs|developer\.", (source.url or "")):
            source.kind = SourceKind.DOCUMENTATION
        else:
            source.kind = SourceKind.WEB_PAGE

    # -- extraction ---------------------------------------------------
    async def extract(self, url: str) -> Source:
        allowed, reason = await is_allowed(url)
        if not allowed:
            raise AccessDenied(f"Refusing to fetch {url}: {reason}", detail={"url": url})

        client = await get_http_client()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the user
            raise ProviderFailed(f"Could not fetch {url}: {exc}", detail={"url": url}) from exc

        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype == "application/pdf" or url.lower().endswith(".pdf"):
            from ..documents.pdf import parse_pdf_bytes

            src = parse_pdf_bytes(resp.content, title=url.rsplit("/", 1)[-1])
            src.url = str(resp.url)
            src.retrieved_by = f"{self.name}+pdf"
            src.retrieval_note = "PDF fetched from the web and parsed."
            return src
        if ctype and not (ctype.startswith("text/") or "html" in ctype or "xml" in ctype):
            raise UnsupportedContent(
                f"{url} served '{ctype}', which this extractor cannot read as a document.",
                detail={"url": url, "content_type": ctype},
            )
        if len(resp.content) > settings.max_fetch_bytes:
            raise UnsupportedContent(
                f"{url} is larger than the {settings.max_fetch_bytes} byte fetch limit.",
                detail={"url": url, "bytes": len(resp.content)},
            )

        soup = BeautifulSoup(resp.text, "lxml")
        return self._build(soup, str(resp.url), robots_reason=reason)

    def _build(self, soup: BeautifulSoup, url: str, *, robots_reason: str) -> Source:
        head_title = normalise(soup.title.string) if soup.title and soup.title.string else ""
        title = (
            self._metas(soup, "citation_title", "dc.title", "og:title", "twitter:title")
            or [head_title]
        )[0] or url

        authors_raw = self._metas(soup, "citation_author", "dc.creator", "author", "article:author")
        for block in self._json_ld(soup):
            node = block.get("author")
            if isinstance(node, dict) and node.get("name"):
                authors_raw.append(node["name"])
            elif isinstance(node, list):
                authors_raw.extend(n.get("name") for n in node if isinstance(n, dict) and n.get("name"))

        pub_raw = (
            self._metas(soup, "citation_publication_date", "citation_date", "dc.date",
                        "article:published_time", "datePublished", "og:published_time")
            or []
        )
        doi = next(iter(self._metas(soup, "citation_doi", "dc.identifier")), None)
        if doi:
            m = _DOI_RE.search(doi)
            doi = m.group(0) if m else None
        if not doi:
            m = _DOI_RE.search(soup.get_text(" ")[:20000])
            doi = m.group(0) if m else None

        description = next(
            iter(self._metas(soup, "description", "og:description", "citation_abstract",
                             "dc.description")),
            None,
        )

        src = Source(
            title=title,
            url=url,
            doi=doi,
            authors=[Author.parse(a) for a in dict.fromkeys(filter(None, authors_raw))][:40],
            container_title=next(iter(self._metas(soup, "citation_journal_title", "og:site_name")), None),
            publisher=next(iter(self._metas(soup, "citation_publisher", "dc.publisher")), None),
            published=_parse_date(pub_raw[0] if pub_raw else None),
            volume=next(iter(self._metas(soup, "citation_volume")), None),
            issue=next(iter(self._metas(soup, "citation_issue")), None),
            language=(soup.html.get("lang") if soup.html else None),
            abstract=description,
            retrieved_by=self.name,
            full_text_retrieved=True,
            retrieval_note=f"Page fetched and parsed. {robots_reason}",
        )
        src.site_name = src.container_title or src.domain
        first, last = (
            next(iter(self._metas(soup, "citation_firstpage")), None),
            next(iter(self._metas(soup, "citation_lastpage")), None),
        )
        if first:
            src.pages = f"{first}-{last}" if last else first
        self._classify(src, soup)

        # -- body text --------------------------------------------------
        for tag in soup.find_all(_DROP):
            tag.decompose()
        root = None
        for hint in _MAIN_HINTS:
            root = soup.select_one(hint)
            if root and len(root.get_text(" ", strip=True)) > 400:
                break
            root = None
        root = root or soup.body or soup

        headings = [normalise(h.get_text(" ")) for h in root.find_all(["h1", "h2", "h3"])][:40]
        body = normalise(root.get_text("\n"))
        for start, end, text in chunk(body)[:120]:
            src.passages.append(
                Passage(source_id=src.id, text=text, char_start=start, char_end=end)
            )

        # -- tables (spec §4.7) ----------------------------------------
        tables = []
        for i, table in enumerate(root.find_all("table")[:20]):
            rows = [
                [normalise(cell.get_text(" ")) for cell in tr.find_all(["th", "td"])]
                for tr in table.find_all("tr")
            ]
            rows = [r for r in rows if any(r)]
            if len(rows) >= 2:
                caption = table.find("caption")
                tables.append(
                    {
                        "index": i,
                        "caption": normalise(caption.get_text(" ")) if caption else None,
                        "header": rows[0],
                        "rows": rows[1:],
                    }
                )

        # -- outbound references (spec §4.8) ---------------------------
        refs = []
        for a in root.find_all("a", href=True)[:600]:
            href = a["href"]
            if href.startswith(("http://", "https://")) and (
                "doi.org" in href or "pubmed" in href or "arxiv.org" in href
            ):
                refs.append({"text": normalise(a.get_text(" "))[:200], "href": href})

        src.extra.update(
            {
                "headings": headings,
                "tables": tables,
                "linked_references": refs[:80],
                "word_count": len(body.split()),
            }
        )
        return src
