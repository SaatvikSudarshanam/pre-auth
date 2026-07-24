"""TOON: Token Object Optimization Notation

Comprehensive token reduction across the pre-auth pipeline via:
1. Compact JSON schemas (field abbreviations, null removal)
2. Field whitelisting (agent-specific context)
3. Response templating (compact formats)
4. Hierarchical abstraction (summaries vs full detail)
5. Token budgeting & tracking
"""
from __future__ import annotations

import json
from typing import Any, Dict


# ============================================================================
# TOON FIELD ABBREVIATIONS: Standard mappings for all contexts
# ============================================================================

FIELD_ABBREV = {
    # Claim
    "claim_id": "cid",
    "claim_type": "ct",
    "provider_name": "pn",
    "date_of_service": "dos",
    "diagnosis_text": "dx",
    "amount": "amt",
    "status": "st",
    # Plan
    "plan_name": "pln",
    "plan_code": "pc",
    "annual_limit": "lim",
    "deductible": "ded",
    "copay_percent": "copay",
    "preauth_required": "pa_req",
    # Identity
    "full_name": "nm",
    "dob": "dob",
    "member_id": "mid",
    "email": "em",
    # Document
    "doc_type": "dt",
    "filename": "fn",
    "text": "txt",
    # Results
    "registered": "reg",
    "reference": "ref",
    "summary": "sum",
    "issues": "iss",
    "complete": "cpl",
    "present": "prs",
    "missing": "miss",
    "required": "req",
    "identity_match": "id_match",
    "integrity_verdict": "int_verd",
    "integrity_risk": "int_risk",
    "ai_confidence": "conf",
    "reasoning_summary": "rsn",
    "policy_citations": "cit",
    "customer_message": "msg",
}

REVERSE_ABBREV = {v: k for k, v in FIELD_ABBREV.items()}


# ============================================================================
# TOON COMPACT SERIALIZATION
# ============================================================================

def compact_serialize(obj: Any) -> str:
    """Serialize with abbreviations and null removal."""
    return json.dumps(
        _abbreviate(obj),
        separators=(",", ":"),
        default=str,
    )


def compact_deserialize(data: str) -> Dict:
    """Deserialize and expand abbreviations."""
    obj = json.loads(data)
    return _expand(obj)


def _abbreviate(obj: Any) -> Any:
    """Recursively abbreviate field names and remove nulls."""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if v is None or v == "" or v == [] or v == {}:
                continue  # Drop empty values
            short_k = FIELD_ABBREV.get(k, k)
            result[short_k] = _abbreviate(v)
        return result
    elif isinstance(obj, list):
        return [_abbreviate(item) for item in obj]
    elif isinstance(obj, float):
        return round(obj, 2)  # Compact floats
    return obj


def _expand(obj: Any) -> Any:
    """Recursively expand abbreviations back to full names."""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            full_k = REVERSE_ABBREV.get(k, k)
            result[full_k] = _expand(v)
        return result
    elif isinstance(obj, list):
        return [_expand(item) for item in obj]
    return obj


# ============================================================================
# AGENT-SPECIFIC CONTEXT WHITELISTING
# ============================================================================

# Sub-field names here MUST match the *full* keys produced by
# services.context.build_claim_context(). Token savings come from (a) giving each
# agent only its relevant slice, (b) sending document text to just the one agent
# that needs it, and (c) compact JSON — not from renaming input keys, which would
# hurt LLM comprehension in an adjudication task.
AGENT_CONTEXT_FIELDS = {
    "registration": {
        "claim": ["claim_id", "claim_type", "provider_name", "date_of_service", "diagnosis_text", "amount"],
        "identity": ["full_name", "dob", "member_id"],
        "documents": "brief",  # Only filenames + types, not full text
    },
    "completeness": {
        "claim": ["claim_id", "claim_type"],
        "completeness": ["required", "present", "missing", "complete"],
        "documents": "names_only",  # Just list of doc types
    },
    "document_integrity": {
        "claim": ["claim_id", "claim_type", "amount"],
        "identity": ["full_name", "dob", "member_id"],
        "identity_signals": True,      # deterministic OCR / name-match signals
        "documents_text": True,        # the only agent that needs raw document text
    },
    "coverage": {
        "claim": ["claim_id", "claim_type", "amount", "diagnosis_text"],
        "plan_rules": ["plan_name", "plan_code", "annual_limit", "deductible", "copay_percent", "preauth_required", "rules"],
        "financials": ["annual_limit", "used_amount_this_year", "remaining_limit", "claim_amount"],
    },
    "pre_authorization": {
        "claim": ["claim_id", "claim_type", "amount", "date_of_service"],
        "plan_rules": ["annual_limit", "deductible", "copay_percent", "preauth_required", "rules"],
        "financials": ["annual_limit", "used_amount_this_year", "remaining_limit", "claim_amount"],
        "prior_agents": True,  # Include all upstream findings
    },
    "denial": {
        "claim": ["claim_id", "claim_type", "amount"],
        "prior_agents": True,  # Only needs verdict + reasoning
    },
}


def whitelist_context(context: Dict, agent_key: str) -> Dict:
    """Return only the fields relevant to a specific agent."""
    whitelist = AGENT_CONTEXT_FIELDS.get(agent_key, {})
    result = {}

    for field, allowed in whitelist.items():
        if field not in context:
            continue

        if allowed is True:
            result[field] = context[field]
        elif isinstance(allowed, list):
            # Abbreviate and include only allowed sub-fields
            result[field] = {
                k: v for k, v in context[field].items() if k in allowed
            }
        elif allowed == "brief":
            result[field] = _summarize_documents(context.get(field, []), brief=True)
        elif allowed == "names_only":
            result[field] = _summarize_documents(context.get(field, []), names_only=True)
        elif allowed == "full":
            result[field] = context[field]

    return result


def _summarize_documents(docs, brief=False, names_only=False):
    """Summarize documents for token efficiency."""
    if names_only:
        return [d.get("fn") for d in docs] if isinstance(docs, list) else []
    elif brief:
        return [{"fn": d.get("fn"), "dt": d.get("dt")} for d in docs] if isinstance(docs, list) else []
    return docs


# ============================================================================
# TOKEN TRACKING & BUDGETING
# ============================================================================

class TokenBudget:
    """Track token usage per agent."""

    def __init__(self, budget_per_agent: int = 1000):
        self.budget = budget_per_agent
        self.usage: Dict[str, int] = {}
        self.total = 0

    def record(self, agent_key: str, prompt_tokens: int, output_tokens: int):
        """Record token usage for an agent."""
        total = prompt_tokens + output_tokens
        self.usage[agent_key] = total
        self.total += total
        return total

    def check_budget(self, agent_key: str) -> bool:
        """Return True if agent is within budget."""
        return self.usage.get(agent_key, 0) <= self.budget

    def report(self) -> Dict:
        """Return usage summary."""
        return {
            "total_tokens": self.total,
            "per_agent": self.usage,
            "agents_over_budget": [
                k for k, v in self.usage.items() if v > self.budget
            ],
        }


# ============================================================================
# PROGRESSIVE SUMMARIZATION
# ============================================================================

def summarize_documents_text(text: str, max_chars: int = 500) -> str:
    """Truncate document text for agents that don't need full detail."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[... truncated ...]"


# Verbose, adjudication-irrelevant rule keys we can safely drop to save tokens.
# We use a denylist (not an allowlist) so no coverage-relevant rule is ever lost:
# dropping the wrong rule would blind the Coverage / Pre-Auth agents.
_RULE_DROP_KEYS = {"notes", "description", "disclaimer"}


def summarize_plan_rules(rules_json: Dict) -> Dict:
    """Drop only verbose, non-adjudication rule keys; keep all coverage constraints."""
    if not isinstance(rules_json, dict):
        return rules_json
    return {k: v for k, v in rules_json.items() if k.lower() not in _RULE_DROP_KEYS}
