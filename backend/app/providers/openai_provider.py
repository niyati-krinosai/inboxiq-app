import json

from app.config import get_settings
from app.core.logging import get_logger
from app.providers.openai_client import create_openai_client
from app.providers.base import (
    ChatProvider,
    ChatResult,
    EmbeddingProvider,
    ExtractionProvider,
    ExtractionResult,
    LLMUsage,
    RerankerProvider,
)

log = get_logger(__name__)

settings = get_settings()


def _client():
    return create_openai_client()


class OpenAIExtractionProvider(ExtractionProvider):
    async def extract(self, content: str, system_prompt: str, prompt_version: str) -> ExtractionResult:
        client = _client()
        if not client:
            return ExtractionResult(data={}, usage=LLMUsage(model=settings.openai_model, provider="openai"))

        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content[:12000]},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        usage = response.usage
        return ExtractionResult(
            data=json.loads(response.choices[0].message.content or "{}"),
            usage=LLMUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                model=settings.openai_model,
                provider="openai",
            ),
        )


class OpenAIEmbeddingProvider(EmbeddingProvider):
    async def embed(self, text: str) -> tuple[list[float] | None, LLMUsage]:
        client = _client()
        if not client:
            return None, LLMUsage(model=settings.embedding_model, provider="openai")

        try:
            response = await client.embeddings.create(
                model=settings.embedding_model,
                input=text[:8000],
            )
            tokens = response.usage.total_tokens if response.usage else 0
            return response.data[0].embedding, LLMUsage(
                embedding_tokens=tokens,
                model=settings.embedding_model,
                provider="openai",
            )
        except Exception as exc:
            log.warning("openai_embedding_failed", error=str(exc))
            return None, LLMUsage(
                embedding_tokens=0,
                model=settings.embedding_model,
                provider="openai",
            )


class OpenAIChatProvider(ChatProvider):
    async def complete_json(self, system: str, user: str, prompt_version: str) -> ChatResult:
        client = _client()
        if not client:
            return ChatResult(data={}, usage=LLMUsage(model=settings.openai_model, provider="openai"))

        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        usage = response.usage
        return ChatResult(
            data=json.loads(response.choices[0].message.content or "{}"),
            usage=LLMUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                model=settings.openai_model,
                provider="openai",
            ),
        )


class KeywordRerankerProvider(RerankerProvider):
    """Default reranker — keyword overlap (no LLM cost)."""

    def rerank(self, query: str, items: list, score_fn=None) -> list:
        if score_fn:
            return sorted(items, key=score_fn, reverse=True)
        q_tokens = set(query.lower().split())
        def score(item):
            text = str(getattr(item, "headline", "")) + str(getattr(item, "primary_summary", ""))
            text = text.lower()
            return sum(1 for t in q_tokens if len(t) > 3 and t in text)
        return sorted(items, key=score, reverse=True)
