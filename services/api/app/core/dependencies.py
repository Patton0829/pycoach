from functools import lru_cache

from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.mock import DemoMockLLMProvider
from app.llm.openai_compatible import OpenAICompatibleLLMProvider


@lru_cache
def get_llm_provider() -> LLMProvider:
    if settings.llm_provider == "mock":
        return DemoMockLLMProvider()
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleLLMProvider(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            extra_body=settings.llm_extra_body,
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
