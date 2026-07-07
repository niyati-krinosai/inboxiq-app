from openai import AsyncOpenAI

from app.config import get_settings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def create_openai_client() -> AsyncOpenAI | None:
    """Shared OpenAI-compatible client (OpenAI, OpenRouter, etc.)."""
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    kwargs: dict = {"api_key": settings.openai_api_key}
    base_url = settings.openai_base_url
    if not base_url and settings.openai_api_key.startswith("sk-or-"):
        base_url = OPENROUTER_BASE_URL
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncOpenAI(**kwargs)
