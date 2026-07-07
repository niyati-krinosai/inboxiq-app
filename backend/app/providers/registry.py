from functools import lru_cache

from app.providers.base import ChatProvider, EmbeddingProvider, ExtractionProvider, RerankerProvider
from app.providers.openai_provider import (
    KeywordRerankerProvider,
    OpenAIChatProvider,
    OpenAIEmbeddingProvider,
    OpenAIExtractionProvider,
)


@lru_cache
def get_extraction_provider() -> ExtractionProvider:
    return OpenAIExtractionProvider()


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return OpenAIEmbeddingProvider()


@lru_cache
def get_chat_provider() -> ChatProvider:
    return OpenAIChatProvider()


@lru_cache
def get_reranker_provider() -> RerankerProvider:
    return KeywordRerankerProvider()
