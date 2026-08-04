"""Pydantic request/response models."""
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field


# ---- Auth ---------------------------------------------------------------
class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AdminLoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    profile_complete: bool = True


class ProfileIn(BaseModel):
    full_name: str = Field(min_length=1)
    dob: str
    plan_id: int
    phone: Optional[str] = None


class NotifyCallIn(BaseModel):
    action: str
    customer_message: str = Field(min_length=1)


# ---- Plans --------------------------------------------------------------
class PlanOut(BaseModel):
    id: int
    name: str
    code: str
    monthly_premium: float
    annual_limit: float
    deductible: float
    copay_percent: float
    preauth_required: bool
    rules_json: dict

    class Config:
        from_attributes = True


# ---- Users --------------------------------------------------------------
class MeOut(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    phone: Optional[str] = None
    dob: Optional[str]
    member_id: Optional[str]
    plan: Optional[PlanOut]
    profile_complete: bool
    used_amount: float = 0
    remaining_limit: Optional[float] = None
    claim_count: int = 0


# ---- Claims -------------------------------------------------------------
class ClaimCreateIn(BaseModel):
    claim_type: str
    provider_name: str = Field(min_length=1)
    diagnosis_text: Optional[str] = ""
    date_of_service: str
    amount: float = Field(ge=0)


class DocumentOut(BaseModel):
    id: int
    doc_type: str
    filename: str
    uploaded_at: Any

    class Config:
        from_attributes = True


class ClaimEventOut(BaseModel):
    status: str
    note: Optional[str]
    created_at: Any

    class Config:
        from_attributes = True


class ClaimOut(BaseModel):
    id: int
    claim_type: str
    provider_name: str
    diagnosis_text: Optional[str]
    date_of_service: Optional[str]
    amount: float
    status: str
    customer_message: Optional[str]
    created_at: Any
    updated_at: Any
    documents: list[DocumentOut] = []
    events: list[ClaimEventOut] = []
    required_documents: list[str] = []
    missing_documents: list[str] = []

    class Config:
        from_attributes = True


class CompletenessOut(BaseModel):
    required: list[str]
    present: list[str]
    missing: list[str]
    complete: bool


# ---- Admin --------------------------------------------------------------
class AIReviewOut(BaseModel):
    id: int
    provider: str
    model: str
    verdict: str
    ai_score: int
    deterministic_score: int
    final_score: int
    reasoning_summary: Optional[str]
    flags_json: list
    raw_output_json: dict
    created_at: Any
    score_breakdown: Optional[dict] = None
    customer_message_suggestion: Optional[str] = None
    policy_citations: list = []
    integrity: Optional[dict] = None
    agents: list = []

    class Config:
        from_attributes = True


class DecisionIn(BaseModel):
    action: str  # approved | rejected | requested_info
    customer_message: str = Field(min_length=1)
    agreed_with_ai: Optional[bool] = None
