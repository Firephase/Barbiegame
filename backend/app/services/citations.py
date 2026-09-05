"""Citation formatting — APA 7, MLA 9, Chicago 17 (notes-bibliography),
IEEE, Vancouver, and BibTeX.

Formatters never invent a field.  Where a required element is genuinely absent
from the retrieved metadata, the style's own convention for that case is used
("n.d." for an undated work in APA, for example) rather than a plausible
guess — an invented year in a reference list is a fabricated citation.
"""
from __future__ import annotations

import re
from typing import Callable

from ..core.provenance import Author, Source, SourceKind

STYLES = ("apa", "mla", "chicago", "ieee", "vancouver", "bibtex")

STYLE_LABELS = {
    "apa": "APA 7th edition",
    "mla": "MLA 9th edition",
    "chicago": "Chicago 17th (notes–bibliography)",
    "ieee": "IEEE",
    "vancouver": "Vancouver",
    "bibtex": "BibTeX",
}


# ---------------------------------------------------------------------------
# name helpers
# ---------------------------------------------------------------------------
def _initials(given: str | None) -> str:
    if not given:
        return ""
    parts = [p for p in re.split(r"[\s.\-]+", given) if p]
    return " ".join(f"{p[0].upper()}." for p in parts)


def _initials_tight(given: str | None) -> str:
    if not given:
        return ""
    return "".join(p[0].upper() for p in re.split(r"[\s.\-]+", given) if p)


def _family(a: Author) -> str:
    return a.family or a.name


def _apa_names(authors: list[Author]) -> str:
    if not authors:
        return ""
    formatted = [f"{_family(a)}, {_initials(a.given)}".strip().rstrip(",") for a in authors[:20]]
    if len(authors) == 1:
        return formatted[0]
    if len(authors) <= 20:
        return ", ".join(formatted[:-1]) + f", & {formatted[-1]}"
    head = ", ".join(formatted[:19])
    last = f"{_family(authors[-1])}, {_initials(authors[-1].given)}".strip().rstrip(",")
    return f"{head}, ... {last}"


def _mla_names(authors: list[Author]) -> str:
    if not authors:
        return ""
    first = f"{_family(authors[0])}, {authors[0].given}".strip().rstrip(",")
    if len(authors) == 1:
        return first
    if len(authors) == 2:
        second = f"{authors[1].given or ''} {_family(authors[1])}".strip()
        return f"{first}, and {second}"
    return f"{first}, et al"


def _chicago_names(authors: list[Author]) -> str:
    if not authors:
        return ""
    first = f"{_family(authors[0])}, {authors[0].given}".strip().rstrip(",")
    if len(authors) == 1:
        return first
    rest = [f"{a.given or ''} {_family(a)}".strip() for a in authors[1:10]]
    if len(authors) <= 10:
        return first + ", " + ", ".join(rest[:-1]) + (f", and {rest[-1]}" if len(rest) > 1 else f", and {rest[0]}") \
            if len(rest) > 1 else f"{first}, and {rest[0]}"
    return f"{first}, et al"


def _ieee_names(authors: list[Author]) -> str:
    if not authors:
        return ""
    out = [f"{_initials(a.given)} {_family(a)}".strip() for a in authors[:6]]
    if len(authors) > 6:
        return ", ".join(out) + ", et al."
    if len(out) == 1:
        return out[0]
    return ", ".join(out[:-1]) + f", and {out[-1]}"


def _vancouver_names(authors: list[Author]) -> str:
    if not authors:
        return ""
    out = [f"{_family(a)} {_initials_tight(a.given)}".strip() for a in authors[:6]]
    return ", ".join(out) + (", et al" if len(authors) > 6 else "")


# ---------------------------------------------------------------------------
# shared bits
# ---------------------------------------------------------------------------
def _title(source: Source) -> str:
    return source.title.rstrip(". ")


def _venue(source: Source) -> str:
    return source.container_title or source.site_name or source.publisher or ""


def _doi_url(source: Source) -> str:
    return f"https://doi.org/{source.doi}" if source.doi else (source.url or "")


def _is_web(source: Source) -> bool:
    return source.kind in (
        SourceKind.WEB_PAGE, SourceKind.NEWS, SourceKind.GOVERNMENT,
        SourceKind.INSTITUTIONAL, SourceKind.DOCUMENTATION, SourceKind.VIDEO,
    )


def _sentence_case(text: str) -> str:
    """APA/Vancouver want sentence case; preserve obvious acronyms and proper nouns."""
    words = text.split()
    out = []
    for i, w in enumerate(words):
        if i == 0 or w.isupper() or (len(w) > 1 and w[1:].lower() != w[1:]):
            out.append(w)
        else:
            out.append(w.lower())
    return " ".join(out)


# ---------------------------------------------------------------------------
# formatters
# ---------------------------------------------------------------------------
def apa(source: Source) -> str:
    names = _apa_names(source.authors) or _venue(source) or "[No author]"
    year = source.published.year if source.published else "n.d."
    date_part = f"({year}"
    if _is_web(source) and source.published:
        date_part += f", {source.published:%B %-d}" if source.kind == SourceKind.NEWS else ""
    date_part += ")."
    title = _sentence_case(_title(source))

    if source.kind in (SourceKind.JOURNAL_ARTICLE, SourceKind.PREPRINT):
        bits = [f"{names} {date_part} {title}."]
        venue = _venue(source)
        if venue:
            vol = f", {source.volume}" if source.volume else ""
            iss = f"({source.issue})" if source.issue else ""
            pages = f", {source.pages}" if source.pages else ""
            bits.append(f"*{venue}*{vol}{iss}{pages}.")
        if source.kind == SourceKind.PREPRINT:
            bits.append("[Preprint].")
        link = _doi_url(source)
        if link:
            bits.append(link)
        return " ".join(bits)

    if source.kind == SourceKind.VIDEO:
        return " ".join(
            filter(None, [f"{names} {date_part}", f"*{title}* [Video].", _venue(source) + "." if _venue(source) else "", source.url or ""])
        )

    bits = [f"{names} {date_part} *{title}*."]
    venue = _venue(source)
    if venue and venue not in names:
        bits.append(f"{venue}.")
    if source.url:
        bits.append(source.url)
    return " ".join(bits)


def mla(source: Source) -> str:
    names = _mla_names(source.authors)
    prefix = f"{names}. " if names else ""
    title = f'"{_title(source)}."'
    venue = _venue(source)
    bits = [prefix + title]
    if venue:
        bits.append(f"*{venue}*,")
    if source.volume:
        bits.append(f"vol. {source.volume},")
    if source.issue:
        bits.append(f"no. {source.issue},")
    if source.published:
        bits.append(f"{source.published:%-d %b. %Y},".replace("May.", "May"))
    if source.pages:
        bits.append(f"pp. {source.pages},")
    link = _doi_url(source)
    if link:
        bits.append(f"{link}.")
    text = " ".join(bits).rstrip(",. ") + "."
    if _is_web(source):
        text += f" Accessed {source.accessed:%-d %b. %Y}."
    return text


def chicago(source: Source) -> str:
    names = _chicago_names(source.authors)
    prefix = f"{names}. " if names else ""
    title = f'"{_title(source)}."'
    venue = _venue(source)
    bits = [prefix + title]
    if venue:
        bits.append(f"*{venue}*")
    if source.volume:
        bits.append(f"{source.volume}," if not source.issue else f"{source.volume}, no. {source.issue}")
    if source.published:
        bits.append(f"({source.published:%B %Y})" if venue else f"{source.published:%B %-d, %Y}")
    if source.pages:
        bits.append(f": {source.pages}")
    link = _doi_url(source)
    if link:
        bits.append(f". {link}")
    text = " ".join(bits).replace(" :", ":").replace(" .", ".").rstrip(". ") + "."
    if _is_web(source) and not source.doi:
        text = text.rstrip(".") + f". Accessed {source.accessed:%B %-d, %Y}."
    return text


def ieee(source: Source) -> str:
    names = _ieee_names(source.authors)
    bits = [f"{names}," if names else ""]
    bits.append(f'"{_title(source)},"')
    venue = _venue(source)
    if venue:
        bits.append(f"*{venue}*,")
    if source.volume:
        bits.append(f"vol. {source.volume},")
    if source.issue:
        bits.append(f"no. {source.issue},")
    if source.pages:
        bits.append(f"pp. {source.pages},")
    bits.append(f"{source.published:%b. %Y}." if source.published else "n.d.")
    link = _doi_url(source)
    if link:
        bits.append(f"doi: {source.doi}." if source.doi else f"[Online]. Available: {link}")
    return " ".join(b for b in bits if b).replace(" ,", ",")


def vancouver(source: Source) -> str:
    names = _vancouver_names(source.authors)
    bits = [f"{names}." if names else ""]
    bits.append(f"{_sentence_case(_title(source))}.")
    venue = _venue(source)
    if venue:
        bits.append(f"{venue}.")
    if source.published:
        tail = f"{source.published:%Y}"
        if source.volume:
            tail += f";{source.volume}"
            if source.issue:
                tail += f"({source.issue})"
            if source.pages:
                tail += f":{source.pages}"
        bits.append(tail + ".")
    else:
        bits.append("[date unknown].")
    if source.doi:
        bits.append(f"doi:{source.doi}")
    elif source.url:
        bits.append(f"Available from: {source.url}")
    return " ".join(b for b in bits if b)


_BIBTEX_TYPES = {
    SourceKind.JOURNAL_ARTICLE: "article",
    SourceKind.PREPRINT: "misc",
    SourceKind.BOOK: "book",
    SourceKind.DATASET: "misc",
    SourceKind.VIDEO: "misc",
}


def _bibtex_key(source: Source) -> str:
    first = _family(source.authors[0]).lower() if source.authors else "anon"
    first = re.sub(r"[^a-z0-9]", "", first) or "anon"
    year = source.published.year if source.published else "nd"
    word = next(
        (re.sub(r"[^a-z0-9]", "", w.lower()) for w in source.title.split() if len(w) > 3), "work"
    )
    return f"{first}{year}{word}"


def bibtex(source: Source) -> str:
    entry_type = _BIBTEX_TYPES.get(source.kind, "misc" if _is_web(source) else "article")
    if _is_web(source) and source.kind != SourceKind.VIDEO and not source.doi:
        entry_type = "online"
    fields: list[tuple[str, str]] = [("title", "{" + source.title + "}")]
    if source.authors:
        fields.append(("author", " and ".join(
            f"{_family(a)}, {a.given}" if a.given else _family(a) for a in source.authors
        )))
    venue = _venue(source)
    if venue:
        fields.append(("journal" if entry_type == "article" else "howpublished", venue))
    if source.published:
        fields.append(("year", str(source.published.year)))
        fields.append(("month", f"{source.published:%b}".lower()))
    for name, value in (
        ("volume", source.volume), ("number", source.issue), ("pages", source.pages),
        ("publisher", source.publisher), ("doi", source.doi), ("url", source.url),
        ("language", source.language), ("note", "Preprint — not peer reviewed"
         if source.kind == SourceKind.PREPRINT else None),
    ):
        if value:
            fields.append((name, str(value)))
    if _is_web(source):
        fields.append(("urldate", f"{source.accessed:%Y-%m-%d}"))
    body = ",\n".join(f"  {k} = {{{v}}}" if not v.startswith("{") else f"  {k} = {v}"
                      for k, v in fields)
    return f"@{entry_type}{{{_bibtex_key(source)},\n{body}\n}}"


_FORMATTERS: dict[str, Callable[[Source], str]] = {
    "apa": apa, "mla": mla, "chicago": chicago,
    "ieee": ieee, "vancouver": vancouver, "bibtex": bibtex,
}


def format_citation(source: Source, style: str = "apa") -> str:
    style = (style or "apa").lower().strip()
    formatter = _FORMATTERS.get(style)
    if formatter is None:
        raise ValueError(f"Unknown citation style '{style}'. Known: {', '.join(STYLES)}")
    return formatter(source)


def format_all(source: Source) -> dict[str, str]:
    return {style: format_citation(source, style) for style in STYLES}


def bibliography(sources: list[Source], style: str = "apa") -> str:
    """A reference list, alphabetised (author-date styles) or numbered (IEEE/Vancouver)."""
    style = (style or "apa").lower()
    if style == "bibtex":
        return "\n\n".join(bibtex(s) for s in sources)
    entries = [format_citation(s, style) for s in sources]
    if style in ("ieee", "vancouver"):
        return "\n".join(f"[{i}] {e}" for i, e in enumerate(entries, start=1))
    return "\n\n".join(sorted(entries, key=str.lower))


def in_text(source: Source, style: str = "apa", *, index: int | None = None) -> str:
    """The marker that appears in running prose."""
    style = (style or "apa").lower()
    if style in ("ieee", "vancouver"):
        return f"[{index}]" if index is not None else "[?]"
    year = source.published.year if source.published else "n.d."
    if not source.authors:
        short = (source.container_title or source.site_name or source.title)[:28]
        return f'("{short}", {year})' if style == "apa" else f'("{short}")'
    family = _family(source.authors[0])
    if len(source.authors) == 1:
        names = family
    elif len(source.authors) == 2 and style != "apa":
        names = f"{family} and {_family(source.authors[1])}"
    elif len(source.authors) == 2:
        names = f"{family} & {_family(source.authors[1])}"
    else:
        names = f"{family} et al."
    if style == "apa":
        return f"({names}, {year})"
    if style == "mla":
        return f"({names})"
    return f"({names} {year})"
