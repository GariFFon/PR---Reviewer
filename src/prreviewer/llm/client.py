"""Thin wrapper around an OpenAI-compatible chat completions endpoint,
pointed at a hosted CodeLlama model by default. Swappable to any other
OpenAI-compatible host purely via LLM_BASE_URL / LLM_MODEL config.
"""

from openai import AsyncOpenAI

from ..config import Settings


class LLMClient:
    def __init__(self, settings: Settings):
        self._model = settings.llm_model
        # The SDK raises eagerly on an empty api_key, which would otherwise crash
        # the worker at startup. An unset key should instead surface as an auth
        # error on the first real call, which review_file() already degrades from.
        # max_retries is explicit (not left at the SDK default) because free-tier
        # OpenRouter models return transient 429s from a shared pool often enough
        # that a single attempt isn't a fair test of whether the model works.
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "unset",
            max_retries=5,
            timeout=60.0,
        )

    async def complete(self, system_prompt: str, user_message: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=0.1,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content or ""
