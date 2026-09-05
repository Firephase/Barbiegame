"""Anthropic Claude adapter."""
from __future__ import annotations

from ...config import settings
from ...core.errors import ProviderFailed
from ...core.registry import ProviderStatus
from .base import LlmProvider, LlmRequest, LlmResult, parse_json_payload


class AnthropicLlm(LlmProvider):
    name = "anthropic"
    priority = 10
    supports_vision = True

    def status(self) -> ProviderStatus:
        if not settings.anthropic_api_key:
            return ProviderStatus(False, "ANTHROPIC_API_KEY is not set.")
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return ProviderStatus(False, "The 'anthropic' package is not installed.")
        return ProviderStatus(
            True,
            details={"model": settings.anthropic_model, "vision": True},
        )

    def _model(self, tier: str) -> str:
        return settings.anthropic_fast_model if tier == "fast" else settings.anthropic_model

    async def complete(self, request: LlmRequest) -> LlmResult:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        system = request.system
        if request.json_schema:
            system = (
                f"{system}\n\nRespond with a single JSON object and nothing else. "
                f"It must conform to this schema:\n{request.json_schema}"
            ).strip()

        messages = []
        for msg in request.messages:
            if msg.images:
                blocks: list[dict] = []
                for img in msg.images:
                    if img.label:
                        blocks.append({"type": "text", "text": f"[{img.label}]"})
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": img.media_type,
                                "data": img.data_b64,
                            },
                        }
                    )
                if msg.content:
                    blocks.append({"type": "text", "text": msg.content})
                messages.append({"role": msg.role, "content": blocks})
            else:
                messages.append({"role": msg.role, "content": msg.content})

        model = self._model(request.tier)
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=system or anthropic.NOT_GIVEN,
                messages=messages,
                stop_sequences=request.stop_sequences or anthropic.NOT_GIVEN,
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderFailed(f"Anthropic request failed: {exc}", detail={"model": model}) from exc

        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        return LlmResult(
            text=text,
            provider=self.name,
            model=model,
            structured=parse_json_payload(text) if request.json_schema else None,
            usage={
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
            stop_reason=resp.stop_reason,
        )
