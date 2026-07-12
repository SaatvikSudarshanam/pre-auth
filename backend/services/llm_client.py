"""Low-level LLM client — the single place that performs network calls to an LLM.

Provider is chosen by LLM_PROVIDER. Only admin-side AI code imports this
(transitively via services.agents / services.ai_review), preserving isolation.
"""
from __future__ import annotations

import json
import time

import httpx

from config import (
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL,
    LLM_PROVIDER,
)

# Transient-error retry policy (rate limits / 5xx / network blips).
_MAX_ATTEMPTS = 4
_BACKOFF_SECONDS = [1.5, 3.0, 6.0]


class LLMError(Exception):
    """Raised when the LLM call cannot be completed."""


def active_model() -> str:
    if LLM_PROVIDER == "groq":
        return GROQ_MODEL
    if LLM_PROVIDER == "claude":
        return "claude-sonnet-5"
    return "unknown"


def chat_json(system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict:
    """Return a parsed JSON object from the model. Raises LLMError on failure."""
    if LLM_PROVIDER == "groq":
        return _groq_chat_json(system_prompt, user_prompt, temperature)
    if LLM_PROVIDER == "claude":
        # TODO: implement Anthropic Messages API here, mirroring the Groq path.
        raise LLMError("ClaudeProvider is not implemented in this demo. Set LLM_PROVIDER=groq.")
    raise LLMError(f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'.")


def _groq_chat_json(system_prompt: str, user_prompt: str, temperature: float) -> dict:
    if not GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not set. Add it to .env to run AI reviews.")
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error = "unknown error"
    for attempt in range(_MAX_ATTEMPTS):
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{GROQ_BASE_URL.rstrip('/')}/chat/completions",
                    json=payload, headers=headers,
                )
        except httpx.HTTPError as exc:
            last_error = f"Network error calling Groq: {exc}"
            _sleep_backoff(attempt)
            continue

        # Retry on rate limits and transient server errors.
        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = f"Groq API error {resp.status_code}: {resp.text[:300]}"
            retry_after = _retry_after_seconds(resp)
            _sleep_backoff(attempt, retry_after)
            continue
        if resp.status_code >= 400:
            raise LLMError(f"Groq API error {resp.status_code}: {resp.text[:400]}")

        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Unexpected Groq response: {resp.text[:400]}") from exc
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model did not return valid JSON: {content[:400]}") from exc

    raise LLMError(f"Groq unavailable after {_MAX_ATTEMPTS} attempts: {last_error}")


def _retry_after_seconds(resp: "httpx.Response") -> float | None:
    val = resp.headers.get("retry-after")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _sleep_backoff(attempt: int, retry_after: float | None = None) -> None:
    if attempt >= _MAX_ATTEMPTS - 1:
        return
    delay = retry_after if retry_after is not None else _BACKOFF_SECONDS[
        min(attempt, len(_BACKOFF_SECONDS) - 1)
    ]
    time.sleep(min(delay, 10))
