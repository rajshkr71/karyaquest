from __future__ import annotations

from abc import ABC, abstractmethod

from llm_gateway.models import LLMRequest, LLMResponse


class LLMProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the stable provider name."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a validated response for a validated request."""
        raise NotImplementedError
