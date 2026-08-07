"""Deterministic scoring — checkable signals, independent of LLM confidence.

The final score blends the model's self-reported confidence with these
hard, auditable checks so a persuasive-but-wrong LLM answer cannot drive the
displayed score on its own.

Components (20 pts each):
  1. all required documents present
  2. claim category covered by the plan
  3. amount within remaining annual limit
  4. no date/amount inconsistency flagged
  5. documents verified authentic (services.document_review)

Component 5 is scored on a curve rather than pass/fail: verification produces a
0-100 risk, and collapsing that to a boolean would score a claim with one
ambiguous OCR character the same as one with a fabricated GSTIN.
"""
from typing import List, Optional, Tuple

from models import Claim, Plan
from services.completeness import check_claim_documents

COMPONENT_POINTS = 20

# claim_type -> coverage category token used in plan.covered_categories
CATEGORY_MAP = {
    "hospitalization": "hospitalization",
    "procedure": "procedures",
    "pharmacy": "pharmacy",
    "preauth_request": "procedures",
}

_INCONSISTENCY_KEYWORDS = ("mismatch", "inconsist", "does not match", "discrepan")


def is_category_covered(plan: Plan, claim_type: str) -> bool:
    covered = [c.lower() for c in (plan.rules_json or {}).get("covered_categories", [])]
    if "all" in covered:
        return True
    category = CATEGORY_MAP.get(claim_type, claim_type)
    return category in covered


def has_inconsistency_flag(flags: List[str]) -> bool:
    for f in flags or []:
        low = str(f).lower()
        if any(k in low for k in _INCONSISTENCY_KEYWORDS):
            return True
    return False


def _authenticity_component(verification: Optional[dict]) -> dict:
    """Score document authenticity from the deterministic verification result.

    Points fall linearly with risk. A missing verification result scores zero,
    not full marks: "we could not check" and "we checked and it was fine" must
    never land on the same number, because the first is what a broken pipeline
    and a hostile upload both look like.
    """
    if not verification:
        return {
            "key": "documents_authentic",
            "label": "Documents verified authentic",
            "passed": False,
            "points": 0,
            "detail": "Document verification did not run",
        }

    risk = max(0, min(100, int(verification.get("risk") or 0)))
    verdict = verification.get("verdict")
    points = 0 if verdict == "suspected_fraud" else round(
        COMPONENT_POINTS * (100 - risk) / 100
    )
    counts = verification.get("counts") or {}
    failed = verification.get("failed_checks") or []

    detail = (
        f"{counts.get('pass', 0)} passed, {counts.get('fail', 0)} failed, "
        f"{counts.get('warn', 0)} warned, {counts.get('unknown', 0)} unverifiable "
        f"(risk {risk}/100)"
    )
    if failed:
        detail += f" — failed: {', '.join(failed)}"

    return {
        "key": "documents_authentic",
        "label": "Documents verified authentic",
        "passed": verdict == "clear",
        "points": points,
        "detail": detail,
    }


def compute_deterministic_score(
    claim: Claim,
    plan: Plan,
    used_amount: float,
    ai_flags: List[str],
    verification: Optional[dict] = None,
) -> Tuple[int, dict]:
    completeness = check_claim_documents(claim, plan)
    docs_ok = completeness["complete"]

    covered = is_category_covered(plan, claim.claim_type)

    remaining_limit = max(0.0, float(plan.annual_limit) - float(used_amount))
    within_limit = float(claim.amount) <= remaining_limit

    no_inconsistency = not has_inconsistency_flag(ai_flags)

    components = [
        {
            "key": "documents_complete",
            "label": "All required documents present",
            "passed": docs_ok,
            "points": COMPONENT_POINTS if docs_ok else 0,
            "detail": (
                "OK" if docs_ok else f"Missing: {', '.join(completeness['missing'])}"
            ),
        },
        {
            "key": "category_covered",
            "label": "Claim category covered by plan",
            "passed": covered,
            "points": COMPONENT_POINTS if covered else 0,
            "detail": (
                CATEGORY_MAP.get(claim.claim_type, claim.claim_type)
                + (" — covered" if covered else " — not covered")
            ),
        },
        {
            "key": "within_limit",
            "label": "Amount within remaining annual limit",
            "passed": within_limit,
            "points": COMPONENT_POINTS if within_limit else 0,
            "detail": f"Amount {claim.amount:.0f} vs remaining {remaining_limit:.0f}",
        },
        {
            "key": "no_inconsistency",
            "label": "No date/amount inconsistency flagged",
            "passed": no_inconsistency,
            "points": COMPONENT_POINTS if no_inconsistency else 0,
            "detail": "Clean" if no_inconsistency else "AI flagged an inconsistency",
        },
        _authenticity_component(verification),
    ]
    total = sum(c["points"] for c in components)
    breakdown = {
        "deterministic_score": total,
        "components": components,
        "remaining_limit": remaining_limit,
        "used_amount": used_amount,
    }
    return total, breakdown


def compute_final_score(ai_confidence: int, deterministic_score: int) -> int:
    ai_c = max(0, min(100, int(ai_confidence)))
    det = max(0, min(100, int(deterministic_score)))
    return round(0.5 * ai_c + 0.5 * det)
