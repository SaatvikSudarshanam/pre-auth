"""The 5-agent pre-authorization pipeline.

Each agent is a focused LLM call with its own prompt file. They run in sequence,
each seeing the upstream agents' findings, and the Pre-Authorization Agent's
output drives the overall verdict. The Denial Communication Agent drafts the
plain-language message for the customer.

Agents (in order):
  1. Claims Registration Agent   — validate & normalize the request
  2. Doc Completeness Agent      — assess supporting documents
  3. Coverage Verification Agent — verify against plan coverage/limits
  4. Pre-Authorization Agent     — adjudicate (advisory verdict)
  5. Denial Communication Agent  — draft the customer message
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from config import BASE_DIR
from services.llm_client import LLMError, active_model, chat_json

PROMPT_DIR = BASE_DIR / "prompts" / "agents"


@dataclass
class AgentSpec:
    key: str
    name: str
    prompt_file: str
    sequence: int


AGENTS: List[AgentSpec] = [
    AgentSpec("registration", "Claims Registration Agent", "registration.txt", 1),
    AgentSpec("completeness", "Doc Completeness Agent", "completeness.txt", 2),
    AgentSpec("document_integrity", "Document Integrity Agent", "integrity.txt", 3),
    AgentSpec("coverage", "Coverage Verification Agent", "coverage.txt", 4),
    AgentSpec("pre_authorization", "Pre-Authorization Agent", "preauthorization.txt", 5),
    AgentSpec("denial", "Denial Communication Agent", "denial.txt", 6),
]


@dataclass
class AgentResult:
    key: str
    name: str
    sequence: int
    status: str            # ok | error
    output: dict = field(default_factory=dict)
    error: str | None = None
    latency_ms: int = 0


@dataclass
class ReviewResult:
    verdict: str
    ai_confidence: int
    reasoning_summary: str
    flags: List[str] = field(default_factory=list)
    policy_citations: List[str] = field(default_factory=list)
    customer_message: str = ""
    integrity_verdict: str = "clear"      # clear | review | suspected_fraud
    integrity_risk: int = 0
    identity_match: bool = True
    raw: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    review: ReviewResult
    agents: List[AgentResult]


def _load(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _render_user(context: dict, prior: dict) -> str:
    parts = [
        "=== CLAIM ===",
        json.dumps(context["claim"], indent=2, default=str),
        "\n=== CLAIMANT PLAN RULES (authoritative policy — do not go beyond these) ===",
        json.dumps(context["plan_rules"], indent=2, default=str),
        "\n=== FINANCIAL CONTEXT ===",
        json.dumps(context["financials"], indent=2, default=str),
        "\n=== DOCUMENT COMPLETENESS (deterministic backend check) ===",
        json.dumps(context["completeness"], indent=2, default=str),
        "\n=== CLAIMANT IDENTITY (account holder this request is logged in as) ===",
        json.dumps(context.get("identity", {}), indent=2, default=str),
        "\n=== DETERMINISTIC IDENTITY SIGNALS (authoritative name cross-check) ===",
        json.dumps(context.get("identity_signals", {}), indent=2, default=str),
        "\n=== EXTRACTED DOCUMENT TEXT ===",
        context["documents_text"],
    ]
    if prior:
        parts.append("\n=== UPSTREAM AGENT FINDINGS ===")
        parts.append(json.dumps(prior, indent=2, default=str))
    parts.append("\nProduce your JSON output now.")
    return "\n".join(parts)


def _norm_verdict(v: str) -> str:
    v = str(v or "").lower().strip()
    return v if v in ("approve", "reject", "needs_info") else "needs_info"


def _clamp_int(v, default=0) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)]


def run_pipeline(context: dict) -> PipelineResult:
    """Run all agents in order. Raises LLMError if any agent fails."""
    prior: dict = {}
    results: List[AgentResult] = []

    for spec in AGENTS:
        system = _load(spec.prompt_file)
        user = _render_user(context, prior)
        start = time.perf_counter()
        try:
            out = chat_json(system, user)
        except LLMError:
            # Surface the failure — a partial pipeline can't produce a sound verdict.
            raise
        latency = int((time.perf_counter() - start) * 1000)
        results.append(
            AgentResult(spec.key, spec.name, spec.sequence, "ok", out, None, latency)
        )
        prior[spec.key] = out

    review = _aggregate(prior)
    return PipelineResult(review=review, agents=results)


def _aggregate(prior: dict) -> ReviewResult:
    preauth = prior.get("pre_authorization", {}) or {}
    coverage = prior.get("coverage", {}) or {}
    completeness = prior.get("completeness", {}) or {}
    integrity = prior.get("document_integrity", {}) or {}
    denial = prior.get("denial", {}) or {}

    flags = _as_list(preauth.get("flags"))
    for exc in _as_list(coverage.get("exclusions_triggered")):
        flags.append(f"exclusion: {exc}")
    for miss in _as_list(completeness.get("missing")):
        flags.append(f"missing document: {miss}")
    for rf in _as_list(integrity.get("red_flags")):
        flags.append(f"integrity: {rf}")

    citations = _as_list(preauth.get("citations")) + _as_list(coverage.get("citations"))
    # de-dup, preserve order
    seen = set()
    citations = [c for c in citations if not (c in seen or seen.add(c))]

    integrity_verdict = str(integrity.get("authenticity_verdict", "clear")).lower().strip()
    if integrity_verdict not in ("clear", "review", "suspected_fraud"):
        integrity_verdict = "review"

    return ReviewResult(
        verdict=_norm_verdict(preauth.get("verdict")),
        ai_confidence=_clamp_int(preauth.get("confidence")),
        reasoning_summary=str(preauth.get("reasoning", "")).strip(),
        flags=flags,
        policy_citations=citations,
        customer_message=str(denial.get("customer_message", "")).strip(),
        integrity_verdict=integrity_verdict,
        integrity_risk=_clamp_int(integrity.get("risk_score")),
        identity_match=bool(integrity.get("identity_match", True)),
        raw={"agents": prior, "model": active_model()},
    )
