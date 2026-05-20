import httpx
import structlog

from csv_dashboard.config import settings

log = structlog.get_logger()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(Exception):
    """Raised when an LLM call fails after all retries."""


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int = 2048,
) -> str:
    """Call OpenRouter and return the assistant message text.

    Raises LLMError on any HTTP error, missing key in response, or JSON
    parse failure.
    """
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    }
    try:
        r = httpx.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log.error("llm_call_failed", model=model, error=str(e))
        raise LLMError(f"LLM call failed: {e}") from e
