"""Capability registry.

Providers register themselves against a *capability* (``web_search``,
``llm``, ``pdf`` ...).  Callers ask the registry for a capability, never for a
vendor.  A provider that lacks credentials reports ``available=False`` with a
human-readable reason instead of blowing up at call time — which is what makes
the /providers health screen useful.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, TypeVar

from .errors import ProviderUnavailable


@dataclass(slots=True)
class ProviderStatus:
    available: bool
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class Provider:
    """Base class for every external-service adapter."""

    capability: str = ""
    name: str = ""
    #: Lower runs first when a capability is served by a fallback chain.
    priority: int = 100
    #: Free/no-credential providers are safe defaults in ``auto`` mode.
    requires_credentials: bool = True

    def status(self) -> ProviderStatus:      # pragma: no cover - trivial default
        return ProviderStatus(True)

    @property
    def available(self) -> bool:
        return self.status().available

    def describe(self) -> dict[str, Any]:
        st = self.status()
        return {
            "capability": self.capability,
            "name": self.name,
            "available": st.available,
            "reason": st.reason,
            "requires_credentials": self.requires_credentials,
            **st.details,
        }


P = TypeVar("P", bound=Provider)


class Registry:
    def __init__(self) -> None:
        self._providers: dict[str, dict[str, Provider]] = {}
        self._factories: dict[tuple[str, str], Callable[[], Provider]] = {}

    # -- registration -------------------------------------------------
    def register(self, provider: Provider) -> Provider:
        if not provider.capability or not provider.name:
            raise ValueError("provider must define capability and name")
        self._providers.setdefault(provider.capability, {})[provider.name] = provider
        return provider

    def register_lazy(self, capability: str, name: str, factory: Callable[[], Provider]) -> None:
        """Defer construction so a missing optional dependency cannot break boot."""
        self._factories[(capability, name)] = factory

    def _materialise(self, capability: str, name: str) -> Provider | None:
        existing = self._providers.get(capability, {}).get(name)
        if existing is not None:
            return existing
        factory = self._factories.get((capability, name))
        if factory is None:
            return None
        try:
            provider = factory()
        except Exception:  # a broken optional dep must not take the app down
            return None
        return self.register(provider)

    # -- lookup -------------------------------------------------------
    def names(self, capability: str) -> list[str]:
        seen = set(self._providers.get(capability, {}))
        seen |= {n for (c, n) in self._factories if c == capability}
        return sorted(seen)

    def all(self, capability: str) -> list[Provider]:
        out = [p for n in self.names(capability) if (p := self._materialise(capability, n))]
        return sorted(out, key=lambda p: (p.priority, p.name))

    def get(self, capability: str, name: str) -> Provider:
        p = self._materialise(capability, name)
        if p is None:
            raise ProviderUnavailable(
                f"No provider named '{name}' is registered for capability '{capability}'.",
                detail={"capability": capability, "known": self.names(capability)},
            )
        return p

    def resolve(self, capability: str, spec: str | None = None) -> list[Provider]:
        """Turn a config spec into an ordered list of *available* providers.

        ``spec`` is ``auto`` (every available provider, cheapest-first),
        ``none`` (explicitly disabled), or a comma-separated ordered list.
        """
        spec = (spec or "auto").strip()
        if spec in ("none", "off", "disabled", ""):
            return []
        if spec == "auto":
            return [p for p in self.all(capability) if p.available]
        chosen: list[Provider] = []
        for name in (n.strip() for n in spec.split(",")):
            if not name:
                continue
            p = self._materialise(capability, name)
            if p is not None and p.available:
                chosen.append(p)
        return chosen

    def require(self, capability: str, spec: str | None = None) -> Provider:
        providers = self.resolve(capability, spec)
        if not providers:
            raise ProviderUnavailable(
                f"No provider is available for '{capability}'.",
                detail={
                    "capability": capability,
                    "requested": spec or "auto",
                    "registered": [p.describe() for p in self.all(capability)],
                },
            )
        return providers[0]

    def health(self, capabilities: Iterable[str] | None = None) -> dict[str, list[dict]]:
        caps = list(capabilities) if capabilities else sorted(
            set(self._providers) | {c for (c, _) in self._factories}
        )
        return {c: [p.describe() for p in self.all(c)] for c in caps}


registry = Registry()
