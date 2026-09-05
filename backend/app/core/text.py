"""Text utilities used by retrieval, grounding and snippet display."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

_WS = re.compile(r"\s+")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[\"'“])")
_WORD = re.compile(r"[a-z0-9][a-z0-9\-_/]*")

# Common English stopwords + hedging verbs that carry no topical signal.
STOPWORDS = frozenset("""
a about above after again against all also am an and any are aren't as at be because been
before being below between both but by can cannot could couldn't did didn't do does doesn't
doing don't down during each few for from further had hadn't has hasn't have haven't having he
her here hers herself him himself his how i if in into is isn't it its itself just me more most
must my no nor not now of off on once only or other ought our ours out over own same shan't she
should shouldn't so some such than that the their theirs them themselves then there these they
this those through to too under until up very was wasn't we were weren't what when where which
while who whom why with won't would wouldn't you your yours yourself yourselves
""".split())


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return _WS.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def content_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in STOPWORDS and len(t) > 2]


def sentences(text: str) -> list[str]:
    text = normalise(text)
    if not text:
        return []
    return [s.strip() for s in _SENT.split(text) if s.strip()]


def overlap_score(claim: str, passage: str) -> float:
    """Fraction of the claim's content words that appear in the passage.

    A blunt instrument on purpose: it is a *floor* on groundedness, not a
    semantic judgement.  Used to flag citations that plainly do not support the
    sentence attached to them.
    """
    c = set(content_tokens(claim))
    if not c:
        return 0.0
    p = set(content_tokens(passage))
    if not p:
        return 0.0
    return len(c & p) / len(c)


def best_snippet(text: str, query: str, *, window: int = 480) -> str:
    """Pick the most query-relevant verbatim window of ``text``."""
    text = normalise(text)
    if len(text) <= window:
        return text
    q = set(content_tokens(query))
    if not q:
        return text[:window].rsplit(" ", 1)[0] + "…"
    sents = sentences(text) or [text]
    best_i, best_score = 0, -1.0
    for i, s in enumerate(sents):
        score = len(q & set(content_tokens(s)))
        if score > best_score:
            best_i, best_score = i, score
    out, i, j = sents[best_i], best_i, best_i
    while len(out) < window and (i > 0 or j < len(sents) - 1):
        if j < len(sents) - 1 and (len(out) + len(sents[j + 1]) <= window or i == 0):
            j += 1
            out = out + " " + sents[j]
        elif i > 0:
            i -= 1
            out = sents[i] + " " + out
        else:
            break
    prefix = "…" if i > 0 else ""
    suffix = "…" if j < len(sents) - 1 else ""
    return f"{prefix}{out.strip()}{suffix}"


def chunk(text: str, *, size: int = 1400, overlap: int = 200) -> list[tuple[int, int, str]]:
    """Split into overlapping char windows aligned to sentence boundaries.

    Returns ``(char_start, char_end, text)`` so every chunk stays locatable in
    the original document — a citation must be re-findable by a human.
    """
    text = normalise(text)
    if not text:
        return []
    if len(text) <= size:
        return [(0, len(text), text)]
    out: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
            if cut > size * 0.5:
                end = start + cut + 1
        out.append((start, end, text[start:end].strip()))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in out if c[2]]


def keywords(text: str, *, limit: int = 12) -> list[str]:
    counts = Counter(content_tokens(text))
    return [w for w, _ in counts.most_common(limit)]


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"
