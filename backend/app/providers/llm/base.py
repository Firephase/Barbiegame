"""LLM capability contract.

The rest of the app talks to *this* interface only.  Reasoning quality varies
by provider, but the grounding guarantees do not: whatever the model returns is
passed through ``services.grounding`` before a user sees it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from ...core.errors import ProviderFailed
from ..base import HttpProvider

CAPABILITY = "llm"

Role = Literal["system", "user", "assistant"]


@dataclass(slots=True)
class ImageBlock:
    """An image handed to a vision-capable model."""

    data_b64: str
    media_type: str = "image/png"
    label: str | None = None


@dataclass(slots=True)
class LlmMessage:
    role: Role
    content: str
    images: list[ImageBlock] = field(default_factory=list)


@dataclass(slots=True)
class LlmRequest:
    messages: list[LlmMessage]
    system: str = ""
    max_tokens: int = 4096
    temperature: float = 0.2
    #: When set, the adapter asks for JSON and ``LlmResult.structured`` is filled.
    json_schema: dict | None = None
    stop_sequences: list[str] = field(default_factory=list)
    #: Hint for adapters that expose more than one model tier.
    tier: Literal["fast", "default", "deep"] = "default"
    #: What the caller is asking for. Adapters that cannot reason (see
    #: ``extractive``) use this to decide whether they can serve the request
    #: honestly, or must decline.
    intent: str = "generic"
    #: Retrieved passages as ``{"label": "S1", "source_id": ..., "text": ...}``.
    #: Reasoning adapters ignore this (the text is already rendered into the
    #: prompt); the extractive adapter quotes from it directly.
    context_passages: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class LlmResult:
    text: str
    provider: str
    model: str
    structured: dict | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None
    #: True when the adapter cannot reason and only rearranged retrieved text.
    extractive_only: bool = False


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_payload(text: str) -> dict | None:
    """Best-effort JSON recovery from a model response."""
    if not text:
        return None
    candidates = [m.group(1) for m in _FENCE.finditer(text)]
    candidates.append(text)
    for raw in candidates:
        raw = raw.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end <= start:
            continue
        for slice_ in (raw, raw[start : end + 1]):
            try:
                parsed = json.loads(slice_)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


class LlmProvider(HttpProvider):
    capability = CAPABILITY
    supports_vision: bool = False
    #: Set on adapters that cannot generate novel prose (see ``extractive``).
    is_extractive: bool = False

    async def complete(self, request: LlmRequest) -> LlmResult:  # pragma: no cover
        raise NotImplementedError

    async def complete_json(self, request: LlmRequest) -> dict:
        result = await self.complete(request)
        payload = result.structured or parse_json_payload(result.text)
        if payload is None:
            raise ProviderFailed(
                f"{self.name} did not return parsable JSON.",
                detail={"provider": self.name, "preview": result.text[:400]},
            )
        return payload
