"""OpenAI-compatible adapter.

Deliberately spoken over plain HTTP rather than a vendor SDK, so it also serves
any endpoint that implements the same wire format (Azure, vLLM, Ollama,
OpenRouter, Together, …) by changing ``OPENAI_BASE_URL``.
"""
from __future__ import annotations

from ...config import settings
from ...core.registry import ProviderStatus
from .base import LlmProvider, LlmRequest, LlmResult, parse_json_payload


class OpenAiCompatibleLlm(LlmProvider):
    name = "openai"
    priority = 20
    supports_vision = True

    def status(self) -> ProviderStatus:
        if not settings.openai_api_key:
            return ProviderStatus(False, "OPENAI_API_KEY is not set.")
        return ProviderStatus(
            True, details={"model": settings.openai_model, "base_url": settings.openai_base_url}
        )

    async def complete(self, request: LlmRequest) -> LlmResult:
        messages: list[dict] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for msg in request.messages:
            if msg.images:
                parts: list[dict] = []
                for img in msg.images:
                    if img.label:
                        parts.append({"type": "text", "text": f"[{img.label}]"})
                    parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{img.media_type};base64,{img.data_b64}"},
                        }
                    )
                if msg.content:
                    parts.append({"type": "text", "text": msg.content})
                messages.append({"role": msg.role, "content": parts})
            else:
                messages.append({"role": msg.role, "content": msg.content})

        payload: dict = {
            "model": settings.openai_model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.stop_sequences:
            payload["stop"] = request.stop_sequences
        if request.json_schema:
            payload["response_format"] = {"type": "json_object"}
            messages[0 if request.system else 0].setdefault("content", "")

        data = await self.request_json(
            "POST",
            settings.openai_base_url.rstrip("/") + "/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
        choice = (data or {}).get("choices", [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        return LlmResult(
            text=text,
            provider=self.name,
            model=(data or {}).get("model", settings.openai_model),
            structured=parse_json_payload(text) if request.json_schema else None,
            usage=(data or {}).get("usage", {}),
            stop_reason=choice.get("finish_reason"),
        )
