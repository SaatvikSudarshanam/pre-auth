"""SQLAlchemy ORM models.

Enums are stored as plain strings for portability. Claims and reviews are
never deleted (audit requirement) — status transitions only.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


def utcnow():
    return datetime.now(timezone.utc)


# ---- Enum value sets (validated at the schema/route layer) --------------
CLAIM_TYPES = ("hospitalization", "procedure", "pharmacy", "preauth_request")
CLAIM_STATUSES = (
    "submitted",
    "under_review",
    "more_info_needed",
    "approved",
    "rejected",
)
DOC_TYPES = (
    "prescription",
    "itemized_bill",
    "discharge_summary",
    "lab_report",
    "id_proof",
    "other",
)
VERDICTS = ("approve", "reject", "needs_info")
ADMIN_ACTIONS = ("approved", "rejected", "requested_info")


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    code = Column(String, unique=True, nullable=False)
    monthly_premium = Column(Float, nullable=False, default=0)
    annual_limit = Column(Float, nullable=False)
    deductible = Column(Float, nullable=False, default=0)
    copay_percent = Column(Float, nullable=False, default=0)
    preauth_required = Column(Boolean, nullable=False, default=False)
    # rules_json: covered_categories[], exclusions[], per_category_limits{},
    #             required_documents{claim_type: [doc types]}, notes
    rules_json = Column(JSON, nullable=False, default=dict)

    users = relationship("User", back_populates="plan")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    # Nullable: Google (OAuth) users have no local password.
    password_hash = Column(String, nullable=True)
    auth_provider = Column(String, nullable=False, default="password")  # password | google
    google_sub = Column(String, unique=True, nullable=True)
    avatar_url = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)  # E.164, e.g. +919876543210 — used for Twilio calls
    dob = Column(String, nullable=True)  # ISO date string
    member_id = Column(String, unique=True, nullable=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    plan = relationship("Plan", back_populates="users")
    claims = relationship("Claim", back_populates="user")


class Claim(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    claim_type = Column(String, nullable=False)
    provider_name = Column(String, nullable=False)
    diagnosis_text = Column(Text, nullable=True)
    date_of_service = Column(String, nullable=True)  # ISO date string
    amount = Column(Float, nullable=False, default=0)
    status = Column(String, nullable=False, default="submitted")
    customer_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="claims")
    documents = relationship(
        "Document", back_populates="claim", order_by="Document.uploaded_at"
    )
    ai_reviews = relationship(
        "AIReview", back_populates="claim", order_by="AIReview.created_at"
    )
    admin_actions = relationship(
        "AdminAction", back_populates="claim", order_by="AdminAction.created_at"
    )
    events = relationship(
        "ClaimEvent", back_populates="claim", order_by="ClaimEvent.created_at"
    )


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    doc_type = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    path = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=utcnow)
    # Content hash — indexed so duplicate-reuse lookups across claims stay cheap.
    sha256 = Column(String, nullable=True, index=True)
    # Cached services.verification envelope. Verification costs an LLM call per
    # document, and a document is immutable once uploaded, so a re-review reuses
    # this instead of paying again.
    verification_json = Column(JSON, nullable=True)
    verified_at = Column(DateTime, nullable=True)

    claim = relationship("Claim", back_populates="documents")


class AIReview(Base):
    __tablename__ = "ai_reviews"

    id = Column(Integer, primary_key=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    verdict = Column(String, nullable=False)
    ai_score = Column(Integer, nullable=False)          # ai_confidence 0-100
    deterministic_score = Column(Integer, nullable=False)
    final_score = Column(Integer, nullable=False)
    reasoning_summary = Column(Text, nullable=True)
    flags_json = Column(JSON, nullable=False, default=list)
    raw_output_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utcnow)

    claim = relationship("Claim", back_populates="ai_reviews")


class AgentRun(Base):
    """One row per AI agent invocation within a review (full audit)."""

    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    ai_review_id = Column(Integer, ForeignKey("ai_reviews.id"), nullable=True)
    agent_key = Column(String, nullable=False)     # e.g. pre_authorization
    agent_name = Column(String, nullable=False)    # e.g. Pre-Authorization Agent
    sequence = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="ok")  # ok | error
    output_json = Column(JSON, nullable=False, default=dict)
    error_text = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    claim = relationship("Claim")


class Consent(Base):
    """Privacy / cookie consent tracking. user_id null for pre-login (anon) events."""

    __tablename__ = "consents"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    anon_id = Column(String, nullable=True)         # client-generated id before login
    policy = Column(String, nullable=False)         # cookie | privacy
    version = Column(String, nullable=False)
    accepted = Column(Boolean, nullable=False, default=True)
    categories_json = Column(JSON, nullable=False, default=dict)  # e.g. {analytics: true}
    user_agent = Column(String, nullable=True)
    ip = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id = Column(Integer, primary_key=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    action = Column(String, nullable=False)
    reason_text = Column(Text, nullable=True)
    agreed_with_ai = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    claim = relationship("Claim", back_populates="admin_actions")


class ClaimEvent(Base):
    """Status-change timeline entries shown to the customer."""

    __tablename__ = "claim_events"

    id = Column(Integer, primary_key=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    status = Column(String, nullable=False)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    claim = relationship("Claim", back_populates="events")
