"""Extensible LLM Provider Registry."""

from __future__ import annotations

from typing import Dict, List, Optional

from app.providers.anthropic_adapter import AnthropicAdapter
from app.providers.base import BaseProviderAdapter
from app.providers.gemini_adapter import GeminiAdapter
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.types import ModelSpec


class ProviderRegistry:
    """Central registry of LLM provider adapters.

    New providers can be integrated cleanly via `provider_registry.register(CustomAdapter())`.
    """

    def __init__(self) -> None:
        self._adapters: Dict[str, BaseProviderAdapter] = {}

    def register(self, adapter: BaseProviderAdapter) -> None:
        self._adapters[adapter.provider_key] = adapter

    def get(self, provider_key: str) -> BaseProviderAdapter:
        key = provider_key.lower().strip()
        if key not in self._adapters:
            raise KeyError(f"Unsupported LLM provider: '{provider_key}'")
        return self._adapters[key]

    def has(self, provider_key: str) -> bool:
        return provider_key.lower().strip() in self._adapters

    def list_adapters(self) -> List[BaseProviderAdapter]:
        return list(self._adapters.values())

    def list_keys(self) -> List[str]:
        return list(self._adapters.keys())

    def get_model_spec(self, provider_key: str, model_id: str) -> Optional[ModelSpec]:
        if not self.has(provider_key):
            return None
        return self.get(provider_key).get_model_spec(model_id)


provider_registry = ProviderRegistry()
provider_registry.register(OpenAIAdapter())
provider_registry.register(GeminiAdapter())
provider_registry.register(AnthropicAdapter())
