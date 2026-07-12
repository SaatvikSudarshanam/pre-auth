"""Privacy / cookie consent tracking.

Consent events are recorded whether or not the visitor is logged in. If a valid
customer token is present, the event is linked to that user; otherwise a
client-generated anonymous id is stored.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import COOKIE_POLICY_VERSION, PRIVACY_POLICY_VERSION
from database import get_db
from models import Consent
from security import decode_token

router = APIRouter(prefix="/api", tags=["consent"])


class ConsentIn(BaseModel):
    policy: str = "cookie"           # cookie | privacy
    version: Optional[str] = None
    accepted: bool = True
    categories: dict = {}
    anon_id: Optional[str] = None


def _maybe_user_id(request: Request) -> Optional[int]:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        payload = decode_token(auth.split(" ", 1)[1])
        if payload.get("role") == "customer":
            return int(payload["sub"])
    except Exception:
        return None
    return None


@router.get("/policies")
def policy_versions():
    return {
        "privacy_version": PRIVACY_POLICY_VERSION,
        "cookie_version": COOKIE_POLICY_VERSION,
    }


@router.post("/consent")
def record_consent(body: ConsentIn, request: Request, db: Session = Depends(get_db)):
    version = body.version or (
        PRIVACY_POLICY_VERSION if body.policy == "privacy" else COOKIE_POLICY_VERSION
    )
    consent = Consent(
        user_id=_maybe_user_id(request),
        anon_id=body.anon_id,
        policy=body.policy,
        version=version,
        accepted=body.accepted,
        categories_json=body.categories or {},
        user_agent=request.headers.get("User-Agent", "")[:400],
        ip=request.client.host if request.client else None,
    )
    db.add(consent)
    db.commit()
    db.refresh(consent)
    return {"ok": True, "id": consent.id, "version": version}
