"""Multi-LLM abstraction — switch providers without changing business logic."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    embedding_tokens: int = 0
    model: str = ""
    provider: str = ""


@dataclass
class ExtractionResult:
    data: dict
    usage: LLMUsage


@dataclass
class ChatResult:
    data: dict
    usage: LLMUsage


class ExtractionProvider(ABC):
    @abstractmethod
    async def extract(self, content: str, system_prompt: str, prompt_version: str) -> ExtractionResult:
        ...


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> tuple[list[float] | None, LLMUsage]:
        ...


class ChatProvider(ABC):
    @abstractmethod
    async def complete_json(self, system: str, user: str, prompt_version: str) -> ChatResult:
        ...


class RerankerProvider(ABC):
    @abstractmethod
    def rerank(self, query: str, items: list, score_fn=None) -> list:
        ...
