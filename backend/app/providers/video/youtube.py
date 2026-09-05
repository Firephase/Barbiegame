"""Public video transcripts, timestamp-anchored.

We use publicly published captions only.  When a video has none, the app says
so plainly — it does not pretend to have "watched" anything.
"""
from __future__ import annotations

import re

from ...core.errors import AccessDenied, ProviderFailed
from ...core.provenance import Author, Passage, Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import normalise
from ..base import HttpProvider

CAPABILITY = "video_transcript"

_ID_PATTERNS = (
    re.compile(r"(?:youtube\.com/watch\?(?:.*&)?v=)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtu\.be/)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com/(?:embed|shorts|live)/)([A-Za-z0-9_-]{11})"),
)

OEMBED = "https://www.youtube.com/oembed"


def video_id(url: str) -> str | None:
    for pattern in _ID_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return re.fullmatch(r"[A-Za-z0-9_-]{11}", url.strip()).group(0) if re.fullmatch(
        r"[A-Za-z0-9_-]{11}", url.strip()
    ) else None


class YouTubeTranscripts(HttpProvider):
    capability = CAPABILITY
    name = "youtube"
    requires_credentials = False
    priority = 10

    def status(self) -> ProviderStatus:
        try:
            import youtube_transcript_api  # noqa: F401
        except ImportError:
            return ProviderStatus(False, "youtube-transcript-api is not installed.")
        return ProviderStatus(
            True,
            details={
                "uses": "publicly published captions only",
                "note": "Videos without captions cannot be analysed.",
            },
        )

    def handles(self, url: str) -> bool:
        return video_id(url) is not None

    async def _metadata(self, url: str) -> dict:
        try:
            data = await self.request_json(
                "GET", OEMBED, params={"url": url, "format": "json"}, retries=1
            )
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def fetch(self, url: str, *, languages: list[str] | None = None) -> Source:
        vid = video_id(url)
        if not vid:
            raise ProviderFailed(f"'{url}' is not a recognisable YouTube video URL.")

        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
        )

        wanted = languages or ["en", "en-US", "en-GB"]
        try:
            listing = YouTubeTranscriptApi.list_transcripts(vid)
            try:
                transcript = listing.find_manually_created_transcript(wanted)
                generated = False
            except NoTranscriptFound:
                transcript = listing.find_transcript(wanted)
                generated = transcript.is_generated
            entries = transcript.fetch()
            language = transcript.language_code
        except TranscriptsDisabled as exc:
            raise AccessDenied(
                "Captions are disabled for this video, so its content cannot be analysed. "
                "Nothing about what is said in it can be verified from here.",
                detail={"video_id": vid},
            ) from exc
        except (NoTranscriptFound, VideoUnavailable) as exc:
            raise AccessDenied(
                f"No transcript is available for this video ({type(exc).__name__}).",
                detail={"video_id": vid},
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderFailed(f"Transcript retrieval failed: {exc}", detail={"video_id": vid}) from exc

        meta = await self._metadata(f"https://www.youtube.com/watch?v={vid}")
        src = Source(
            kind=SourceKind.VIDEO,
            title=normalise(meta.get("title") or f"YouTube video {vid}"),
            url=f"https://www.youtube.com/watch?v={vid}",
            authors=[Author(name=meta["author_name"])] if meta.get("author_name") else [],
            container_title="YouTube",
            site_name="YouTube",
            publisher=meta.get("author_name"),
            language=language,
            retrieved_by=self.name,
            full_text_retrieved=True,
            retrieval_note=(
                "Auto-generated captions — wording may be inaccurate, "
                "especially for technical terms."
                if generated
                else "Publisher-supplied captions."
            ),
            extra={
                "video_id": vid,
                "auto_generated_captions": generated,
                "thumbnail": meta.get("thumbnail_url"),
                "channel_url": meta.get("author_url"),
            },
        )

        # Group caption cues into ~45s passages so timestamps stay meaningful.
        window, current, start_at = 45.0, [], None
        duration = 0.0
        for entry in entries:
            text = normalise(entry.get("text", ""))
            begin = float(entry.get("start", 0.0))
            length = float(entry.get("duration", 0.0))
            duration = max(duration, begin + length)
            if start_at is None:
                start_at = begin
            current.append(text)
            if begin + length - start_at >= window:
                joined = normalise(" ".join(current))
                if joined:
                    src.passages.append(
                        Passage(source_id=src.id, text=joined,
                                start_seconds=start_at, end_seconds=begin + length)
                    )
                current, start_at = [], None
        if current and start_at is not None:
            joined = normalise(" ".join(current))
            if joined:
                src.passages.append(
                    Passage(source_id=src.id, text=joined, start_seconds=start_at, end_seconds=duration)
                )

        src.extra["duration_seconds"] = round(duration, 1)
        src.extra["cue_count"] = len(entries)
        src.abstract = normalise(" ".join(p.text for p in src.passages[:3]))[:1200] or None
        return src

    @staticmethod
    def timestamp_url(source: Source, seconds: float) -> str | None:
        vid = source.extra.get("video_id")
        return f"https://www.youtube.com/watch?v={vid}&t={int(seconds)}s" if vid else None
