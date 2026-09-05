"""Zero-credential fallback: extraction without generation.

This adapter cannot write prose, and that is the point.  With no LLM key
configured the workspace still performs real research — search, fetch, parse,
rank, cite — and answers by *quoting* the passages it actually retrieved,
labelled with their source.  It is the strongest possible anti-hallucination
guarantee: there is no generative step in which a fact could be invented.

When an operation genuinely needs reasoning (synthesis across papers, image
interpretation, diagram authoring), it declines and says which key to set,
rather than producing something plausible and unfounded.
"""
from __future__ import annotations

import json

from ...core.errors import ProviderUnavailable
from ...core.registry import ProviderStatus
from ...core.text import content_tokens, sentences
from .base import LlmProvider, LlmRequest, LlmResult

#: Intents this adapter can serve truthfully by quoting alone.
EXTRACTIVE_INTENTS = {"answer", "generic", "summarise", "quote"}


class ExtractiveLlm(LlmProvider):
    name = "extractive"
    priority = 900          # last resort in ``auto`` mode
    requires_credentials = False
    is_extractive = True
    supports_vision = False

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            True,
            details={
                "generates_prose": False,
                "note": (
                    "No reasoning model configured. Answers are verbatim quotes from "
                    "retrieved sources; synthesis, image analysis and diagram authoring "
                    "are unavailable."
                ),
            },
        )

    def _question(self, request: LlmRequest) -> str:
        for msg in reversed(request.messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return ""

    async def complete(self, request: LlmRequest) -> LlmResult:
        if request.intent not in EXTRACTIVE_INTENTS:
            raise ProviderUnavailable(
                f"The '{request.intent}' operation needs a reasoning model, and none is "
                f"configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY to enable it. "
                f"Search, retrieval, citation, statistics and charting all work without it.",
                detail={"intent": request.intent, "fallback": self.name},
            )

        question = self._question(request)
        wanted = set(content_tokens(question))
        scored: list[tuple[float, str, dict]] = []
        for passage in request.context_passages:
            for sentence in sentences(passage.get("text", "")):
                if len(sentence) < 40:
                    continue
                terms = set(content_tokens(sentence))
                if not terms:
                    continue
                hits = len(wanted & terms)
                if not hits:
                    continue
                # Favour sentences dense in the question's terms, not merely long ones.
                scored.append((hits / (len(terms) ** 0.5), sentence, passage))

        scored.sort(key=lambda row: row[0], reverse=True)
        picked: list[tuple[str, dict]] = []
        seen: set[str] = set()
        for _, sentence, passage in scored:
            key = sentence[:80].lower()
            if key in seen:
                continue
            seen.add(key)
            picked.append((sentence, passage))
            if len(picked) >= 8:
                break

        claims = [
            {
                "text": sentence,
                "status": "verified",
                "sources": [passage.get("label")] if passage.get("label") else [],
                "quote": sentence,
            }
            for sentence, passage in picked
        ]
        labels = sorted({p.get("label") for _, p in picked if p.get("label")})
        summary = (
            f"No reasoning model is configured, so this answer is assembled from "
            f"{len(picked)} verbatim passage(s) across {len(labels)} source(s), "
            f"selected for overlap with your question. Nothing here is paraphrased "
            f"or inferred."
            if picked
            else "No retrieved passage matched this question closely enough to quote. "
            "Nothing is being inferred to fill the gap."
        )

        payload = {
            "summary": summary,
            "claims": claims,
            "disagreements": [],
            "open_questions": [],
            "limitations": [
                "Answer is extractive: sentences are quoted, not synthesised.",
                "Cross-source reasoning, contradiction detection and interpretation "
                "require a configured reasoning model.",
            ],
        }
        text = json.dumps(payload, indent=2) if request.json_schema else "\n\n".join(
            f"{s} [{p.get('label', '?')}]" for s, p in picked
        ) or summary

        return LlmResult(
            text=text,
            provider=self.name,
            model="extractive-v1",
            structured=payload if request.json_schema else None,
            usage={"passages_considered": len(request.context_passages)},
            stop_reason="end_turn",
            extractive_only=True,
        )
