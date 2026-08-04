"""Customer routes (/api/*).

IMPORTANT: nothing in this module imports services.ai_review or references the
LLM in any way. The customer surface is AI-free by construction.
"""
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from config import ALLOWED_MIME, MAX_UPLOAD_BYTES
from database import get_db
from models import (
    CLAIM_TYPES,
    DOC_TYPES,
    Claim,
    ClaimEvent,
    Document,
    Plan,
    User,
    utcnow,
)
from schemas import (
    ClaimCreateIn,
    ClaimOut,
    CompletenessOut,
    MeOut,
    PlanOut,
    ProfileIn,
)
from security import get_current_user
from services.completeness import check_claim_documents, required_doc_types
from services.documents import store_upload

router = APIRouter(prefix="/api", tags=["customer"])


# ---- helpers ------------------------------------------------------------
def _used_amount(db: Session, user_id: int) -> float:
    total = 0.0
    for c in db.query(Claim).filter(
        Claim.user_id == user_id, Claim.status == "approved"
    ):
        total += float(c.amount or 0)
    return total


def _claim_out(claim: Claim, plan: Plan | None) -> ClaimOut:
    required = required_doc_types(plan, claim.claim_type) if plan else []
    present = {d.doc_type for d in claim.documents}
    missing = [d for d in required if d not in present]
    out = ClaimOut.model_validate(claim)
    out.required_documents = required
    out.missing_documents = missing
    return out


# ---- plans --------------------------------------------------------------
@router.get("/plans", response_model=List[PlanOut])
def list_plans(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Plan).order_by(Plan.id).all()


# ---- profile ------------------------------------------------------------
@router.get("/me", response_model=MeOut)
def me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    used = _used_amount(db, user.id)
    remaining = (float(user.plan.annual_limit) - used) if user.plan else None
    claim_count = (
        db.query(Claim)
        .filter(Claim.user_id == user.id, Claim.status != "draft")
        .count()
    )
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        dob=user.dob,
        member_id=user.member_id,
        plan=PlanOut.model_validate(user.plan) if user.plan else None,
        profile_complete=bool(user.full_name and user.plan_id and user.member_id),
        used_amount=used,
        remaining_limit=remaining,
        claim_count=claim_count,
    )


@router.post("/me/profile", response_model=MeOut)
def complete_profile(
    body: ProfileIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = db.get(Plan, body.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    user.full_name = body.full_name.strip()
    user.dob = body.dob
    user.plan_id = plan.id
    if body.phone is not None:
        user.phone = body.phone.strip() or None
    if not user.member_id:
        user.member_id = f"MEM-2026-{user.id:04d}"
    db.commit()
    db.refresh(user)
    return me(db, user)


# ---- claims -------------------------------------------------------------
@router.get("/claims", response_model=List[ClaimOut])
def list_claims(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    claims = (
        db.query(Claim)
        .filter(Claim.user_id == user.id, Claim.status != "draft")
        .order_by(Claim.created_at.desc())
        .all()
    )
    return [_claim_out(c, user.plan) for c in claims]


def _load_owned_claim(db: Session, claim_id: int, user: User) -> Claim:
    claim = db.get(Claim, claim_id)
    if not claim or claim.user_id != user.id:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


@router.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    claim = _load_owned_claim(db, claim_id, user)
    return _claim_out(claim, user.plan)


@router.post("/claims", response_model=ClaimOut)
def create_claim(
    body: ClaimCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.plan_id:
        raise HTTPException(status_code=400, detail="Complete your profile first")
    if body.claim_type not in CLAIM_TYPES:
        raise HTTPException(status_code=422, detail="Invalid claim type")
    claim = Claim(
        user_id=user.id,
        claim_type=body.claim_type,
        provider_name=body.provider_name.strip(),
        diagnosis_text=(body.diagnosis_text or "").strip(),
        date_of_service=body.date_of_service,
        amount=body.amount,
        status="draft",  # internal; becomes 'submitted' only after doc check passes
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return _claim_out(claim, user.plan)


@router.get("/claims/{claim_id}/completeness", response_model=CompletenessOut)
def claim_completeness(
    claim_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    claim = _load_owned_claim(db, claim_id, user)
    return CompletenessOut(**check_claim_documents(claim, user.plan))


@router.post("/claims/{claim_id}/documents", response_model=ClaimOut)
async def upload_document(
    claim_id: int,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    claim = _load_owned_claim(db, claim_id, user)
    if claim.status in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Claim is closed")
    if doc_type not in DOC_TYPES:
        raise HTTPException(status_code=422, detail="Invalid document type")
    if (file.content_type or "").lower() not in ALLOWED_MIME:
        raise HTTPException(
            status_code=415, detail="Only PDF, JPG, and PNG files are allowed"
        )
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 15 MB)")

    path, fname = store_upload(content, file.content_type, file.filename)
    doc = Document(
        claim_id=claim.id, doc_type=doc_type, filename=file.filename or fname, path=path
    )
    db.add(doc)

    # Uploading fresh evidence while info was requested puts it back under review.
    if claim.status == "more_info_needed":
        claim.status = "under_review"
        claim.updated_at = utcnow()
        db.add(ClaimEvent(claim_id=claim.id, status="under_review",
                          note="Customer uploaded additional documents"))
    db.commit()
    db.refresh(claim)
    return _claim_out(claim, user.plan)


@router.post("/claims/{claim_id}/submit", response_model=ClaimOut)
def submit_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    claim = _load_owned_claim(db, claim_id, user)
    if claim.status not in ("draft",):
        raise HTTPException(status_code=400, detail="Claim already submitted")

    # Deterministic doc-completeness gate — NOT the LLM.
    result = check_claim_documents(claim, user.plan)
    if not result["complete"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Missing required documents",
                "missing": result["missing"],
                "required": result["required"],
            },
        )
    claim.status = "submitted"
    claim.updated_at = utcnow()
    db.add(ClaimEvent(claim_id=claim.id, status="submitted", note="Claim submitted"))
    db.commit()
    db.refresh(claim)
    return _claim_out(claim, user.plan)
