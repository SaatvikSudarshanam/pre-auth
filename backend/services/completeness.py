"""Document-completeness rule check.

This is a PURE, deterministic backend rule — it never calls the LLM. It reads
the required document types for a claim type from the claimant's plan rules and
compares them against the documents actually attached to the claim.
"""
from typing import List

from models import Claim, Plan


def required_doc_types(plan: Plan, claim_type: str) -> List[str]:
    rules = plan.rules_json or {}
    required_map = rules.get("required_documents", {}) or {}
    return list(required_map.get(claim_type, []))


def check_claim_documents(claim: Claim, plan: Plan) -> dict:
    required = required_doc_types(plan, claim.claim_type)
    present = sorted({d.doc_type for d in claim.documents})
    missing = [d for d in required if d not in present]
    return {
        "required": required,
        "present": present,
        "missing": missing,
        "complete": len(missing) == 0,
    }
