"""The 5-agent pre-authorization pipeline.

Each agent is a focused LLM call with its own prompt file. They run in sequence,
each seeing the upstream agents' findings, and the Pre-Authorization Agent's
output drives the overall verdict. The Denial Communication Agent drafts the
plain-language message for the customer.

TOON Optimization: Field whitelisting, compact JSON, token tracking.

Agents (in order):
  1. Claims Registration Agent   — validate & normalize the request
  2. Doc Completeness Agent      — assess supporting documents
  3. Doc Integrity Agent         — verify document authenticity
  4. Coverage Verification Agent — verify against plan coverage/limits
  5. Pre-Authorization Agent     — adjudicate (advisory verdict)
  6. Denial Communication Agent  — draft the customer message
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from config import BASE_DIR
from services.llm_client import LLMError, active_model, chat_json_with_tokens
from services.toon import (
    AGENT_CONTEXT_FIELDS,
    _summarize_documents,
)

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
    tokens: dict = field(default_factory=dict)  # {prompt_tokens, completion_tokens, total_tokens}


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


# Human-readable section headers per context block.
_BLOCK_LABELS = {
    "claim": "CLAIM",
    "plan_rules": "PLAN RULES",
    "financials": "FINANCIALS",
    "completeness": "DOCUMENT COMPLETENESS (deterministic, authoritative)",
    "identity": "ACCOUNT IDENTITY",
    "identity_signals": "IDENTITY SIGNALS (deterministic OCR / name-match)",
    "document_verification": (
        "DOCUMENT VERIFICATION (deterministic, authoritative — forensics, GSTIN "
        "checksum, address, name/provider match)"
    ),
    "documents": "DOCUMENTS",
    "documents_text": "DOCUMENTS",
}

# Values that carry no information — skip the whole block rather than emit "{}"/"[]".
_EMPTY = (None, "", [], {})


def _compact(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)


def _render_user(context: dict, agent_key: str, prior: dict) -> str:
    """Render the user prompt for one agent: only its whitelisted slice, compact JSON.

    Field whitelisting (services.toon.AGENT_CONTEXT_FIELDS) keeps each agent's prompt
    small — most importantly, raw document text goes only to the integrity agent, and
    upstream findings only to agents that opted in via `prior_agents`.
    """
    whitelist = AGENT_CONTEXT_FIELDS.get(agent_key, {})
    parts: list[str] = []

    for field_name, allowed in whitelist.items():
        if field_name == "prior_agents":
            continue  # handled after the loop

        # Raw document text (free text, not JSON).
        if field_name == "documents_text":
            text = context.get("documents_text")
            if text:
                parts.append(f"=== {_BLOCK_LABELS['documents_text']} ===")
                parts.append(str(text))
            continue

        # Document metadata summaries pull from the context's `documents` list.
        if allowed in ("brief", "names_only"):
            docs = context.get("documents", [])
            rendered = _summarize_documents(
                docs,
                brief=(allowed == "brief"),
                names_only=(allowed == "names_only"),
            )
        elif field_name not in context:
            continue
        elif allowed is True:
            rendered = context[field_name]
        elif isinstance(allowed, list) and isinstance(context[field_name], dict):
            rendered = {k: v for k, v in context[field_name].items() if k in allowed}
        else:
            rendered = context[field_name]

        if rendered in _EMPTY:
            continue

        label = _BLOCK_LABELS.get(field_name, field_name.upper())
        parts.append(f"=== {label} ===")
        parts.append(rendered if isinstance(rendered, str) else _compact(rendered))

    # Upstream findings only for agents that requested them (pre-auth, denial).
    # `prior_agents` is either True (all upstream findings) or a list of agent
    # keys — the list form lets a downstream agent take only the slices it needs
    # (e.g. denial reads just the verdict + coverage, not every raw finding).
    prior_spec = whitelist.get("prior_agents")
    if prior_spec and prior:
        if isinstance(prior_spec, list):
            selected = {k: prior[k] for k in prior_spec if k in prior}
        else:
            selected = prior
        if selected:
            parts.append("=== UPSTREAM FINDINGS ===")
            parts.append(_compact(selected))

    parts.append("Respond with valid JSON only.")
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


def _pick(d: dict, *keys, default=None):
    """First present, non-empty value among `keys`.

    Agents emit TOON-abbreviated output keys (verd, conf, rsn, msg, int_verd, ...).
    We read those first and fall back to the full names so the aggregator keeps
    working if a prompt is reverted to verbose keys.
    """
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def run_pipeline(context: dict) -> PipelineResult:
    """Run all agents in order with TOON token optimization. Raises LLMError if any agent fails."""
    prior: dict = {}
    results: List[AgentResult] = []
    total_tokens = 0

    for spec in AGENTS:
        system = _load(spec.prompt_file)
        user = _render_user(context, spec.key, prior)
        start = time.perf_counter()
        try:
            out, tokens = chat_json_with_tokens(system, user)
        except LLMError:
            # Surface the failure — a partial pipeline can't produce a sound verdict.
            raise
        latency = int((time.perf_counter() - start) * 1000)
        total_tokens += tokens.get("total_tokens", 0)
        results.append(
            AgentResult(
                spec.key,
                spec.name,
                spec.sequence,
                "ok",
                out,
                None,
                latency,
                tokens,
            )
        )
        prior[spec.key] = out

    review = _aggregate(prior)
    review.raw["total_tokens"] = total_tokens
    return PipelineResult(review=review, agents=results)


def _aggregate(prior: dict) -> ReviewResult:
    preauth = prior.get("pre_authorization", {}) or {}
    coverage = prior.get("coverage", {}) or {}
    completeness = prior.get("completeness", {}) or {}
    integrity = prior.get("document_integrity", {}) or {}
    denial = prior.get("denial", {}) or {}

    flags = _as_list(_pick(preauth, "flags", default=[]))
    for exc in _as_list(_pick(coverage, "exc", "exclusions_triggered", default=[])):
        flags.append(f"exclusion: {exc}")
    for miss in _as_list(_pick(completeness, "miss", "missing", default=[])):
        flags.append(f"missing document: {miss}")
    for rf in _as_list(_pick(integrity, "flags", "red_flags", default=[])):
        flags.append(f"integrity: {rf}")

    citations = (
        _as_list(_pick(preauth, "cit", "citations", default=[]))
        + _as_list(_pick(coverage, "cit", "citations", default=[]))
    )
    # de-dup, preserve order
    seen = set()
    citations = [c for c in citations if not (c in seen or seen.add(c))]

    integrity_verdict = str(
        _pick(integrity, "int_verd", "authenticity_verdict", default="clear")
    ).lower().strip()
    if integrity_verdict not in ("clear", "review", "suspected_fraud"):
        integrity_verdict = "review"

    return ReviewResult(
        verdict=_norm_verdict(_pick(preauth, "verd", "verdict")),
        ai_confidence=_clamp_int(_pick(preauth, "conf", "confidence")),
        reasoning_summary=str(_pick(preauth, "rsn", "reasoning", "reasoning_summary", default="")).strip(),
        flags=flags,
        policy_citations=citations,
        customer_message=str(_pick(denial, "msg", "customer_message", default="")).strip(),
        integrity_verdict=integrity_verdict,
        integrity_risk=_clamp_int(_pick(integrity, "int_risk", "risk_score", default=0)),
        identity_match=bool(_pick(integrity, "id_match", "identity_match", default=True)),
        raw={"agents": prior, "model": active_model()},
    )
