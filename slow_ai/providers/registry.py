"""Provider adapter registry."""

from __future__ import annotations

from collections.abc import Iterable

from slow_ai.domain.exceptions import RegistryError
from slow_ai.providers.contracts import ProviderAdapter


class ProviderRegistry:
    def __init__(self, adapters: Iterable[ProviderAdapter] = ()) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: ProviderAdapter) -> None:
        provider_name = adapter.provider_name.strip()
        if not provider_name:
            raise RegistryError("Provider name is required.")
        if provider_name in self._adapters:
            raise RegistryError(f"Provider is already registered: {provider_name}")
        self._adapters[provider_name] = adapter

    def get(self, provider_name: str) -> ProviderAdapter:
        try:
            return self._adapters[provider_name]
        except KeyError as exc:
            raise RegistryError(f"Unknown provider: {provider_name}") from exc

    def has(self, provider_name: str) -> bool:
        return provider_name in self._adapters

    def all(self) -> tuple[ProviderAdapter, ...]:
        return tuple(self._adapters.values())


def create_default_provider_registry() -> ProviderRegistry:
    from slow_ai.providers.wavespeed import WaveSpeedAdapter

    return ProviderRegistry([WaveSpeedAdapter()])
