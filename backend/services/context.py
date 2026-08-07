"""Assemble the review context for a claim (plan rules come straight from the DB).

Optimized for TOON (Token Object Optimization Notation):
- Compact field names
- Truncated document text
- Progressive summarization
"""
from sqlalchemy.orm import Session

from models import Claim, User
from services.completeness import check_claim_documents
from services.document_review import summarize_for_agent, verify_claim_documents
from services.documents import extract_document_text
from services.integrity import check_identity
from services.toon import (
    DOC_TEXT_MAX_CHARS,
    summarize_documents_text,
    summarize_plan_rules,
)


def used_annual_amount(db: Session, user_id: int, exclude_claim_id: int | None = None) -> float:
    total = 0.0
    for c in db.query(Claim).filter(Claim.user_id == user_id, Claim.status == "approved"):
        if exclude_claim_id and c.id == exclude_claim_id:
            continue
        total += float(c.amount or 0)
    return total


def build_claim_context(db: Session, claim: Claim, verify_documents: bool = True) -> dict:
    """Assemble everything the agent pipeline reasons over.

    `verify_documents` runs the per-document forensics + extraction + cross-check
    pass (services.document_review). It costs one LLM call per unverified
    document, cached on the Document row thereafter. Turn it off only for
    diagnostics — with it off, the integrity agent sees raw OCR text and no
    deterministic verdict, which is the pre-verification behaviour.
    """
    user: User = claim.user
    plan = user.plan

    blocks = []
    for doc in claim.documents:
        text = extract_document_text(doc.path, doc.filename) or "(no text)"
        blocks.append(f"[{doc.doc_type} :: {doc.filename}]\n{text}")
    documents_text = "\n\n".join(blocks) if blocks else "(no documents attached)"

    completeness = check_claim_documents(claim, plan) if plan else {
        "required": [], "present": [], "missing": [], "complete": False
    }
    used = used_annual_amount(db, user.id, exclude_claim_id=claim.id)

    verification = verify_claim_documents(db, claim) if verify_documents else None

    return {
        "claim": {
            "claim_id": claim.id,
            "claim_type": claim.claim_type,
            "provider_name": claim.provider_name,
            "diagnosis_text": claim.diagnosis_text,
            "date_of_service": claim.date_of_service,
            "amount": claim.amount,
            "status": claim.status,
        },
        "plan_rules": {
            "plan_name": plan.name if plan else None,
            "plan_code": plan.code if plan else None,
            "annual_limit": plan.annual_limit if plan else None,
            "deductible": plan.deductible if plan else None,
            "copay_percent": plan.copay_percent if plan else None,
            "preauth_required": plan.preauth_required if plan else None,
            "rules": plan.rules_json if plan else {},
        },
        "financials": {
            "annual_limit": plan.annual_limit if plan else None,
            "used_amount_this_year": used,
            "remaining_limit": (float(plan.annual_limit) - used) if plan else None,
            "claim_amount": claim.amount,
        },
        "completeness": completeness,
        "identity": {
            "full_name": user.full_name,
            "dob": user.dob,
            "member_id": user.member_id,
            "email": user.email,
        },
        "identity_signals": check_identity(claim),
        # Compact projection for the agents; the full result is kept alongside so
        # the admin route can persist and render it without re-verifying.
        "document_verification": summarize_for_agent(verification) if verification else None,
        "document_verification_full": verification,
        "documents_text": documents_text,
        "used_amount": used,
    }


def build_claim_context_optimized(db: Session, claim: Claim) -> dict:
    """TOON-optimized claim context with truncated documents and summarized rules."""
    context = build_claim_context(db, claim)
    
    # Cap raw document text. Only the integrity agent receives this block, and the
    # authoritative name/identity check (services.integrity.check_identity) already
    # runs on the *full* OCR text — so this cap saves tokens without weakening the
    # fraud gate.
    if "documents_text" in context:
        context["documents_text"] = summarize_documents_text(
            context["documents_text"],
            max_chars=DOC_TEXT_MAX_CHARS,
        )
    
    # Simplify plan rules (only keep coverage-relevant fields)
    if "plan_rules" in context and context["plan_rules"].get("rules"):
        context["plan_rules"]["rules"] = summarize_plan_rules(
            context["plan_rules"]["rules"]
        )
    
    # Store list of document metadata (lighter than full text)
    documents_list = []
    for doc in claim.documents:
        documents_list.append({
            "dt": doc.doc_type,
            "fn": doc.filename,
        })
    context["documents"] = documents_list
    
    return context
