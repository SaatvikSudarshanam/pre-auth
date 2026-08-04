"""Admin routes (/api/admin/*).

This is the ONLY router that imports services.ai_review. Every route here is
guarded by get_current_admin, which rejects customer tokens with 403.
"""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from models import (
    ADMIN_ACTIONS,
    AdminAction,
    AgentRun,
    AIReview,
    Claim,
    ClaimEvent,
    Document,
    Plan,
    User,
    utcnow,
)
from schemas import AIReviewOut, DecisionIn, NotifyCallIn
from security import get_current_admin
from services.ai_review import (
    AIReviewError,
    build_claim_context_optimized,
    get_provider,
)
from services.completeness import check_claim_documents
from services.scoring import compute_deterministic_score, compute_final_score

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(get_current_admin)])

PENDING_STATUSES = ("submitted", "under_review", "more_info_needed")
ACTION_TO_STATUS = {
    "approved": "approved",
    "rejected": "rejected",
    "requested_info": "more_info_needed",
}


def _load_claim(db: Session, claim_id: int) -> Claim:
    claim = db.get(Claim, claim_id)
    if not claim or claim.status == "draft":
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


# ---- queue --------------------------------------------------------------
@router.get("/claims")
def queue(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Claim).filter(Claim.status != "draft")
    if status:
        q = q.filter(Claim.status == status)
    # Oldest-first so the longest-waiting claims surface at the top.
    claims = q.order_by(Claim.created_at.asc()).all()
    rows = []
    for c in claims:
        rows.append({
            "id": c.id,
            "customer": c.user.full_name or c.user.email,
            "customer_email": c.user.email,
            "plan": c.user.plan.name if c.user.plan else None,
            "claim_type": c.claim_type,
            "amount": c.amount,
            "date_of_service": c.date_of_service,
            "status": c.status,
            "docs_count": len(c.documents),
            "created_at": c.created_at,
            "has_ai_review": len(c.ai_reviews) > 0,
        })
    return rows


# ---- stats --------------------------------------------------------------
@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    pending = db.query(Claim).filter(Claim.status.in_(PENDING_STATUSES)).count()

    today = datetime.now(timezone.utc).date()
    decided_today = 0
    for a in db.query(AdminAction).all():
        created = a.created_at
        if created and created.date() == today:
            decided_today += 1

    rated = db.query(AdminAction).filter(AdminAction.agreed_with_ai.isnot(None)).all()
    agreed = sum(1 for a in rated if a.agreed_with_ai)
    agreement_rate = round(100 * agreed / len(rated)) if rated else None

    return {
        "pending": pending,
        "decided_today": decided_today,
        "agreement_rate": agreement_rate,
        "agreement_sample": len(rated),
    }


# ---- claim detail -------------------------------------------------------
def _serialize_review(rev: AIReview, agent_runs: list) -> dict:
    agents = [
        {
            "key": a.agent_key,
            "name": a.agent_name,
            "sequence": a.sequence,
            "status": a.status,
            "output": a.output_json or {},
            "latency_ms": a.latency_ms,
        }
        for a in sorted(
            [a for a in agent_runs if a.ai_review_id == rev.id], key=lambda x: x.sequence
        )
    ]
    return {
        "id": rev.id,
        "provider": rev.provider,
        "model": rev.model,
        "verdict": rev.verdict,
        "ai_score": rev.ai_score,
        "deterministic_score": rev.deterministic_score,
        "final_score": rev.final_score,
        "reasoning_summary": rev.reasoning_summary,
        "flags_json": rev.flags_json or [],
        "raw_output_json": rev.raw_output_json or {},
        "created_at": rev.created_at,
        "score_breakdown": (rev.raw_output_json or {}).get("_score_breakdown"),
        "customer_message_suggestion": (rev.raw_output_json or {}).get("customer_message"),
        "policy_citations": (rev.raw_output_json or {}).get("policy_citations", []),
        "integrity": (rev.raw_output_json or {}).get("_integrity"),
        "agents": agents,
    }


@router.get("/claims/{claim_id}")
def claim_detail(claim_id: int, db: Session = Depends(get_db)):
    claim = _load_claim(db, claim_id)
    user: User = claim.user
    plan: Plan | None = user.plan
    completeness = check_claim_documents(claim, plan) if plan else None

    used = 0.0
    for c in db.query(Claim).filter(Claim.user_id == user.id, Claim.status == "approved"):
        if c.id != claim.id:
            used += float(c.amount or 0)
    remaining = (float(plan.annual_limit) - used) if plan else None

    return {
        "id": claim.id,
        "claim_type": claim.claim_type,
        "provider_name": claim.provider_name,
        "diagnosis_text": claim.diagnosis_text,
        "date_of_service": claim.date_of_service,
        "amount": claim.amount,
        "status": claim.status,
        "customer_message": claim.customer_message,
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
        "customer": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "dob": user.dob,
            "member_id": user.member_id,
        },
        "plan": {
            "name": plan.name if plan else None,
            "code": plan.code if plan else None,
            "annual_limit": plan.annual_limit if plan else None,
            "deductible": plan.deductible if plan else None,
            "copay_percent": plan.copay_percent if plan else None,
            "preauth_required": plan.preauth_required if plan else None,
            "rules_json": plan.rules_json if plan else {},
        },
        "financials": {
            "used_amount": used,
            "remaining_limit": remaining,
            "annual_limit": plan.annual_limit if plan else None,
        },
        "completeness": completeness,
        "documents": [
            {
                "id": d.id,
                "doc_type": d.doc_type,
                "filename": d.filename,
                "uploaded_at": d.uploaded_at,
            }
            for d in claim.documents
        ],
        "ai_reviews": [
            _serialize_review(r, db.query(AgentRun).filter(AgentRun.claim_id == claim.id).all())
            for r in claim.ai_reviews
        ],
        "admin_actions": [
            {
                "id": a.id,
                "action": a.action,
                "reason_text": a.reason_text,
                "agreed_with_ai": a.agreed_with_ai,
                "created_at": a.created_at,
            }
            for a in claim.admin_actions
        ],
        "events": [
            {"status": e.status, "note": e.note, "created_at": e.created_at}
            for e in claim.events
        ],
    }


# ---- document preview ---------------------------------------------------
@router.get("/documents/{document_id}")
def preview_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc or not os.path.exists(doc.path):
        raise HTTPException(status_code=404, detail="Document not found")
    ext = os.path.splitext(doc.path)[1].lower()
    media = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(ext, "application/octet-stream")
    return FileResponse(
        doc.path,
        media_type=media,
        filename=doc.filename,
        content_disposition_type="inline",
    )


# ---- AI review ----------------------------------------------------------
@router.post("/claims/{claim_id}/ai-review", response_model=AIReviewOut)
def run_ai_review(claim_id: int, db: Session = Depends(get_db)):
    claim = _load_claim(db, claim_id)
    if not claim.user.plan:
        raise HTTPException(status_code=400, detail="Claimant has no plan on file")

    context = build_claim_context_optimized(db, claim)
    try:
        provider = get_provider()
        pipeline = provider.review_claim(context)
    except AIReviewError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    result = pipeline.review
    det_score, breakdown = compute_deterministic_score(
        claim, claim.user.plan, context["used_amount"], result.flags
    )
    final = compute_final_score(result.ai_confidence, det_score)

    # --- Integrity hard-gate (deterministic + agent) --------------------------
    # No fake-document claim may auto-approve. If the account holder's name cannot
    # be confirmed against the readable documents, or the integrity agent suspects
    # fraud, block approval, cap the score, and raise a loud flag for the human.
    signals = context.get("identity_signals", {}) or {}
    integrity_blocked = bool(signals.get("hard_mismatch")) or result.integrity_verdict == "suspected_fraud"
    identity_match = result.identity_match and not signals.get("hard_mismatch")
    if integrity_blocked:
        result.flags.insert(
            0,
            "IDENTITY / DOCUMENT INTEGRITY: claimant identity could not be confirmed "
            "against the submitted documents — manual verification required before approval",
        )
        if result.verdict == "approve":
            result.verdict = "needs_info"
        final = min(final, 40)
        identity_match = False

    integrity_summary = {
        "verdict": result.integrity_verdict,
        "risk": result.integrity_risk,
        "identity_match": identity_match,
        "blocked": integrity_blocked,
        "ocr_used": signals.get("ocr_used", False),
        "ocr_score": signals.get("ocr_score"),
        "ocr_mean_confidence": signals.get("ocr_mean_confidence"),
        "deterministic": signals,
        "agent": (result.raw.get("agents", {}) or {}).get("document_integrity", {}),
    }

    raw = dict(result.raw)
    raw["_score_breakdown"] = breakdown  # persisted for audit + tooltip
    raw["_integrity"] = integrity_summary
    raw["customer_message"] = result.customer_message
    raw["policy_citations"] = result.policy_citations

    review = AIReview(
        claim_id=claim.id,
        provider=provider.name,
        model=provider.model,
        verdict=result.verdict,
        ai_score=result.ai_confidence,
        deterministic_score=det_score,
        final_score=final,
        reasoning_summary=result.reasoning_summary,
        flags_json=result.flags,
        raw_output_json=raw,
    )
    db.add(review)
    db.flush()  # need review.id for agent_runs

    # Persist every agent invocation for audit.
    for ar in pipeline.agents:
        db.add(AgentRun(
            claim_id=claim.id,
            ai_review_id=review.id,
            agent_key=ar.key,
            agent_name=ar.name,
            sequence=ar.sequence,
            status=ar.status,
            output_json=ar.output,
            error_text=ar.error,
            latency_ms=ar.latency_ms,
        ))

    # A submitted claim moves to under_review once a human/AI starts looking.
    if claim.status == "submitted":
        claim.status = "under_review"
        claim.updated_at = utcnow()
        db.add(ClaimEvent(claim_id=claim.id, status="under_review",
                          note="AI review run by admin"))
    db.commit()
    db.refresh(review)

    out = AIReviewOut.model_validate(review)
    out.score_breakdown = breakdown
    out.customer_message_suggestion = result.customer_message
    out.integrity = integrity_summary
    out.agents = [
        {
            "key": ar.key,
            "name": ar.name,
            "sequence": ar.sequence,
            "status": ar.status,
            "output": ar.output,
            "latency_ms": ar.latency_ms,
        }
        for ar in pipeline.agents
    ]
    return out


# ---- decision -----------------------------------------------------------
@router.post("/claims/{claim_id}/decision")
def decide(claim_id: int, body: DecisionIn, db: Session = Depends(get_db)):
    claim = _load_claim(db, claim_id)
    if body.action not in ADMIN_ACTIONS:
        raise HTTPException(status_code=422, detail="Invalid action")
    new_status = ACTION_TO_STATUS[body.action]

    claim.status = new_status
    claim.customer_message = body.customer_message.strip()
    claim.updated_at = utcnow()

    db.add(AdminAction(
        claim_id=claim.id,
        action=body.action,
        reason_text=body.customer_message.strip(),
        agreed_with_ai=body.agreed_with_ai,
    ))
    note = {
        "approved": "Claim approved",
        "rejected": "Claim rejected",
        "requested_info": "More information requested",
    }[body.action]
    db.add(ClaimEvent(claim_id=claim.id, status=new_status, note=note))
    db.commit()
    db.refresh(claim)
    return {"id": claim.id, "status": claim.status, "customer_message": claim.customer_message}


CLAIM_TYPE_LABEL = {
    "hospitalization": "Hospitalization",
    "procedure": "Procedure",
    "pharmacy": "Pharmacy",
    "preauth_request": "Pre-Authorization Request",
}


@router.post("/claims/{claim_id}/notify-call")
def notify_call(claim_id: int, body: NotifyCallIn, db: Session = Depends(get_db)):
    print(f"DEBUG: notify_call called for claim {claim_id}", flush=True)
    
    from config import TWILIO_TEST_PHONE_NUMBER, TWILIO_CALLBACK_URL
    from services.twilio_voice import is_twilio_configured, place_decision_call

    print(f"DEBUG: Imported config. callback_url = {TWILIO_CALLBACK_URL}", flush=True)

    if not is_twilio_configured():
        print(f"DEBUG: Twilio not configured", flush=True)
        return {"ok": False, "skipped": True, "reason": "Twilio is not configured"}

    print(f"DEBUG: Loading claim {claim_id}", flush=True)
    claim = _load_claim(db, claim_id)
    user: User = claim.user
    # Use test phone number if customer has no phone on file
    to_phone = user.phone or TWILIO_TEST_PHONE_NUMBER
    print(f"DEBUG: to_phone = {to_phone}", flush=True)

    if body.action not in ADMIN_ACTIONS:
        raise HTTPException(status_code=422, detail="Invalid action")

    claim_type = CLAIM_TYPE_LABEL.get(claim.claim_type, claim.claim_type)
    print(f"DEBUG: About to call place_decision_call", flush=True)
    try:
        call_sid = place_decision_call(
            to_phone=to_phone,
            customer_name=user.full_name,
            claim_id=claim.id,
            action=body.action,
            message=body.customer_message.strip(),
            claim_type=claim_type,
            callback_url=TWILIO_CALLBACK_URL,
        )
        print(f"DEBUG: call_sid = {call_sid}", flush=True)
    except ValueError as exc:
        print(f"DEBUG: ValueError: {exc}", flush=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        # Log error but don't crash — return graceful skip instead of 502
        print(f"WARNING: Twilio call failed for claim {claim_id}: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        return {"ok": False, "skipped": True, "reason": f"Twilio call failed: {exc}"}

    return {"ok": True, "call_sid": call_sid, "phone": to_phone}
