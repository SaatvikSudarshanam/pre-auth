"""Assemble the review context for a claim (plan rules come straight from the DB)."""
from sqlalchemy.orm import Session

from models import Claim, User
from services.completeness import check_claim_documents
from services.documents import extract_document_text
from services.integrity import check_identity


def used_annual_amount(db: Session, user_id: int, exclude_claim_id: int | None = None) -> float:
    total = 0.0
    for c in db.query(Claim).filter(Claim.user_id == user_id, Claim.status == "approved"):
        if exclude_claim_id and c.id == exclude_claim_id:
            continue
        total += float(c.amount or 0)
    return total


def build_claim_context(db: Session, claim: Claim) -> dict:
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
        "documents_text": documents_text,
        "used_amount": used,
    }
