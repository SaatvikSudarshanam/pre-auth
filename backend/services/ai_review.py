"""AI review façade — the public entry point for admin-side AI.

Architectural contract (see README): imported exclusively by admin-authenticated
routes under /api/admin/*. No customer route, and no customer frontend code,
references anything here.

Provider abstraction: `LLMProvider.review_claim(context) -> PipelineResult`.
`GroqProvider` runs the 5-agent pipeline (via services.agents, which selects the
concrete LLM through services.llm_client). `ClaudeProvider` is a stub. The active
provider is chosen by the LLM_PROVIDER env var.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from config import LLM_PROVIDER
from services.agents import PipelineResult, run_pipeline
from services.context import build_claim_context  # re-export
from services.llm_client import LLMError, active_model

# Backwards-compatible alias used by routes.
AIReviewError = LLMError

__all__ = [
    "AIReviewError",
    "LLMProvider",
    "GroqProvider",
    "ClaudeProvider",
    "get_provider",
    "build_claim_context",
    "PipelineResult",
]


class LLMProvider(ABC):
    name = "base"

    @property
    def model(self) -> str:
        return active_model()

    @abstractmethod
    def review_claim(self, claim_context: dict) -> PipelineResult:
        ...


class GroqProvider(LLMProvider):
    name = "groq"

    def review_claim(self, claim_context: dict) -> PipelineResult:
        return run_pipeline(claim_context)


class ClaudeProvider(LLMProvider):
    """Stub — swap-in for Anthropic Claude.

    TODO: implement by pointing services.llm_client at the Anthropic Messages API
    (model e.g. claude-sonnet-5). The 5-agent pipeline is provider-agnostic, so no
    changes are needed here beyond wiring the client.
    """

    name = "claude"

    def review_claim(self, claim_context: dict) -> PipelineResult:  # pragma: no cover
        raise AIReviewError(
            "ClaudeProvider is not implemented in this demo. Set LLM_PROVIDER=groq."
        )


def get_provider() -> LLMProvider:
    if LLM_PROVIDER == "groq":
        return GroqProvider()
    if LLM_PROVIDER == "claude":
        return ClaudeProvider()
    raise AIReviewError(f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. Use 'groq' or 'claude'.")
