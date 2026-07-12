"""Idempotent demo seed.

Creates 3 plans, 2 demo customers, and 3 sample claims in mixed statuses, with
generated PDF documents on disk so both dashboards look alive on first run.
Runs automatically on first start (only if the plans table is empty).
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from config import UPLOAD_DIR
from models import (
    AdminAction,
    AgentRun,
    AIReview,
    Claim,
    ClaimEvent,
    Document,
    Plan,
    User,
)
from security import hash_password

# Required documents per claim type — identical across plans (stored in each
# plan's rules_json so the DB stays the single source of truth).
REQUIRED_DOCS = {
    "hospitalization": ["itemized_bill", "discharge_summary", "id_proof"],
    "procedure": ["prescription", "itemized_bill", "id_proof"],
    "pharmacy": ["prescription", "itemized_bill"],
    "preauth_request": ["prescription", "id_proof"],
}


def _write_text_pdf(lines: list[str]) -> tuple[str, str]:
    """Write a minimal, valid single-page PDF with extractable text.

    Returns (absolute_path, filename). Hand-built so we need no PDF-writer dep.
    """
    ops = "BT /F1 12 Tf 72 720 Td 15 TL\n"
    for ln in lines:
        safe = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops += f"({safe}) Tj T*\n"
    ops += "ET"
    content = ops.encode("latin-1", "replace")

    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(content)).encode() + b">>\nstream\n" + content + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objects) + 1
    out += f"xref\n0 {n}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<</Size " + str(n).encode() + b"/Root 1 0 R>>\nstartxref\n"
        + str(xref_pos).encode() + b"\n%%EOF"
    )

    fname = f"seed-{uuid.uuid4().hex[:8]}.pdf"
    path = UPLOAD_DIR / fname
    with open(path, "wb") as fh:
        fh.write(out)
    return str(path), fname


def _doc(claim: Claim, doc_type: str, human_name: str, lines: list[str]) -> Document:
    path, _ = _write_text_pdf([human_name, ""] + lines)
    return Document(claim_id=claim.id, doc_type=doc_type, filename=f"{human_name}.pdf", path=path)


_AGENT_META = [
    ("registration", "Claims Registration Agent", 1),
    ("completeness", "Doc Completeness Agent", 2),
    ("document_integrity", "Document Integrity Agent", 3),
    ("coverage", "Coverage Verification Agent", 4),
    ("pre_authorization", "Pre-Authorization Agent", 5),
    ("denial", "Denial Communication Agent", 6),
]


def _seed_agent_runs(db, claim_id: int, review_id: int, outputs: dict, when):
    for key, name, seq in _AGENT_META:
        db.add(AgentRun(
            claim_id=claim_id, ai_review_id=review_id, agent_key=key, agent_name=name,
            sequence=seq, status="ok", output_json=outputs.get(key, {}),
            latency_ms=400 + seq * 60, created_at=when,
        ))


def seed_if_empty(db: Session) -> None:
    if db.query(Plan).count() > 0:
        return

    now = datetime.now(timezone.utc)

    basic = Plan(
        name="Basic Care", code="BASIC", monthly_premium=1200,
        annual_limit=200000, deductible=10000, copay_percent=20,
        preauth_required=True,
        rules_json={
            "covered_categories": ["hospitalization", "pharmacy"],
            "exclusions": ["cosmetic", "dental", "pre-existing (first year)"],
            "per_category_limits": {"pharmacy": 25000},
            "required_documents": REQUIRED_DOCS,
            "notes": "Pre-authorization required for all hospitalizations.",
        },
    )
    silver = Plan(
        name="Silver PPO", code="SILVER", monthly_premium=3200,
        annual_limit=500000, deductible=5000, copay_percent=10,
        preauth_required=False,
        rules_json={
            "covered_categories": ["hospitalization", "procedures", "pharmacy", "lab"],
            "exclusions": ["cosmetic"],
            "per_category_limits": {},
            "required_documents": REQUIRED_DOCS,
            "preauth_rules": {"procedures_above_amount": 50000},
            "notes": "Pre-authorization required for procedures above 50,000.",
        },
    )
    gold = Plan(
        name="Gold HMO", code="GOLD", monthly_premium=6000,
        annual_limit=1000000, deductible=0, copay_percent=5,
        preauth_required=False,
        rules_json={
            "covered_categories": ["all"],
            "exclusions": ["cosmetic"],
            "per_category_limits": {},
            "required_documents": REQUIRED_DOCS,
            "notes": "No pre-authorization required.",
        },
    )
    db.add_all([basic, silver, gold])
    db.flush()

    alice = User(
        email="alice@example.com", password_hash=hash_password("Passw0rd!"),
        full_name="Alice Menon", dob="1990-04-12", plan_id=silver.id,
    )
    ravi = User(
        email="ravi@example.com", password_hash=hash_password("Passw0rd!"),
        full_name="Ravi Sharma", dob="1985-11-03", plan_id=basic.id,
    )
    db.add_all([alice, ravi])
    db.flush()
    alice.member_id = f"MEM-2026-{alice.id:04d}"
    ravi.member_id = f"MEM-2026-{ravi.id:04d}"

    # --- Claim 1: Alice, hospitalization, submitted (awaiting review) --------
    c1 = Claim(
        user_id=alice.id, claim_type="hospitalization",
        provider_name="Apollo Hospital, Chennai",
        diagnosis_text="Acute appendicitis; laparoscopic appendectomy",
        date_of_service="2026-06-28", amount=120000, status="submitted",
        created_at=now - timedelta(days=4), updated_at=now - timedelta(days=4),
    )
    db.add(c1); db.flush()
    db.add_all([
        _doc(c1, "itemized_bill", "Itemized Bill", [
            "Apollo Hospital, Chennai", "Patient: Alice Menon  Member: MEM-2026",
            "Date of service: 2026-06-28",
            "Surgery (laparoscopic appendectomy) .... 85,000",
            "Room & nursing (2 days) ................. 22,000",
            "Pharmacy & consumables ................. 13,000",
            "TOTAL ................................. 120,000",
        ]),
        _doc(c1, "discharge_summary", "Discharge Summary", [
            "Diagnosis: Acute appendicitis",
            "Procedure: Laparoscopic appendectomy on 2026-06-28",
            "Condition on discharge: Stable. Advised rest for 7 days.",
        ]),
        _doc(c1, "id_proof", "ID Proof", ["Government ID", "Name: Alice Menon", "DOB: 1990-04-12"]),
    ])
    db.add(ClaimEvent(claim_id=c1.id, status="submitted", note="Claim submitted",
                      created_at=now - timedelta(days=4)))

    # --- Claim 2: Alice, procedure, more_info_needed (round-trip demo) -------
    c2 = Claim(
        user_id=alice.id, claim_type="procedure",
        provider_name="Fortis Clinic, Bengaluru",
        diagnosis_text="Arthroscopy of right knee",
        date_of_service="2026-06-15", amount=65000, status="more_info_needed",
        customer_message=("We need a clearer copy of your itemized bill — the "
                          "current scan is partly illegible. Please re-upload it "
                          "and your claim will resume review."),
        created_at=now - timedelta(days=9), updated_at=now - timedelta(days=2),
    )
    db.add(c2); db.flush()
    db.add_all([
        _doc(c2, "prescription", "Prescription", [
            "Dr. R. Iyer, Orthopedics", "Patient: Alice Menon",
            "Advised: Right knee arthroscopy", "Date: 2026-06-10"]),
        _doc(c2, "itemized_bill", "Itemized Bill", [
            "Fortis Clinic", "Patient: Alice Menon",
            "Arthroscopy right knee ..... 65,000", "Date: 2026-06-15"]),
        _doc(c2, "id_proof", "ID Proof", ["Government ID", "Name: Alice Menon"]),
    ])
    rev2 = AIReview(
        claim_id=c2.id, provider="groq", model="llama-3.3-70b-versatile",
        verdict="needs_info", ai_score=58, deterministic_score=100, final_score=79,
        reasoning_summary=("Procedure (knee arthroscopy) is a covered category under "
                           "Silver PPO and all required documents are present. However "
                           "the amount (65,000) exceeds the 50,000 pre-authorization "
                           "threshold for procedures, and no pre-auth reference is on "
                           "file. Recommend requesting the pre-authorization document."),
        flags_json=["procedure amount above pre-auth threshold"],
        raw_output_json={
            "verdict": "needs_info", "ai_confidence": 58,
            "reasoning_summary": "Procedure covered; pre-auth threshold exceeded.",
            "flags": ["procedure amount above pre-auth threshold"],
            "policy_citations": ["Silver PPO requires pre-authorization for procedures above 50,000"],
            "customer_message": "Your knee procedure is covered, but it needs a pre-authorization document because the amount is above the plan's pre-auth threshold.",
        },
        created_at=now - timedelta(days=2),
    )
    db.add(rev2)
    db.flush()
    _seed_agent_runs(db, c2.id, rev2.id, {
        "registration": {"registered": True, "reference": f"PA-{c2.id}",
                         "summary": "Knee arthroscopy pre-authorization request at Fortis Clinic.",
                         "issues": []},
        "completeness": {"complete": True, "missing": [],
                         "assessment": "All required documents present; bill legibility to confirm.",
                         "confidence": 80},
        "document_integrity": {"authenticity_verdict": "clear", "risk_score": 12,
                               "identity_match": True,
                               "red_flags": [],
                               "document_checks": [{"document": "ID Proof.pdf", "issue": "ok"}],
                               "assessment": "Account holder name Alice Menon matches the ID proof and bills; amounts and dates are consistent."},
        "coverage": {"covered": True, "within_limit": True, "exclusions_triggered": [],
                     "assessment": "Procedures are covered under Silver PPO; amount 65,000 exceeds the 50,000 pre-auth threshold.",
                     "citations": ["Silver PPO requires pre-authorization for procedures above 50,000"]},
        "pre_authorization": {"verdict": "needs_info", "confidence": 58,
                              "reasoning": "Covered procedure but over the pre-auth threshold with no pre-auth on file.",
                              "flags": ["procedure amount above pre-auth threshold"],
                              "citations": ["Silver PPO requires pre-authorization for procedures above 50,000"]},
        "denial": {"customer_message": c2.customer_message, "letter_reference": f"DL-{c2.id}"},
    }, now - timedelta(days=2))
    db.add(AdminAction(claim_id=c2.id, action="requested_info",
                       reason_text=c2.customer_message, agreed_with_ai=True,
                       created_at=now - timedelta(days=2)))
    db.add_all([
        ClaimEvent(claim_id=c2.id, status="submitted", note="Claim submitted",
                   created_at=now - timedelta(days=9)),
        ClaimEvent(claim_id=c2.id, status="under_review", note="AI review run by admin",
                   created_at=now - timedelta(days=3)),
        ClaimEvent(claim_id=c2.id, status="more_info_needed", note="More information requested",
                   created_at=now - timedelta(days=2)),
    ])

    # --- Claim 3: Ravi, pharmacy, approved (audit + agreement demo) ----------
    c3 = Claim(
        user_id=ravi.id, claim_type="pharmacy",
        provider_name="MedPlus Pharmacy",
        diagnosis_text="Type 2 diabetes — monthly medication",
        date_of_service="2026-07-01", amount=3500, status="approved",
        customer_message=("Your pharmacy claim has been approved. After your 20% "
                          "co-pay, the covered amount will be processed to your "
                          "registered account."),
        created_at=now - timedelta(days=6), updated_at=now - timedelta(days=1),
    )
    db.add(c3); db.flush()
    db.add_all([
        _doc(c3, "prescription", "Prescription", [
            "Dr. S. Nair", "Patient: Ravi Sharma", "Metformin 500mg, Glimepiride 1mg",
            "Refill: 1 month", "Date: 2026-07-01"]),
        _doc(c3, "itemized_bill", "Itemized Bill", [
            "MedPlus Pharmacy", "Patient: Ravi Sharma", "Metformin 500mg x60 ..... 1,200",
            "Glimepiride 1mg x30 ..... 2,300", "TOTAL ..... 3,500"]),
    ])
    rev3 = AIReview(
        claim_id=c3.id, provider="groq", model="llama-3.3-70b-versatile",
        verdict="approve", ai_score=88, deterministic_score=100, final_score=94,
        reasoning_summary=("Pharmacy is a covered category under Basic Care and both "
                           "required documents (prescription, itemized bill) are present "
                           "and consistent. The amount (3,500) is well within the annual "
                           "limit and the pharmacy sub-limit. No exclusions apply."),
        flags_json=[],
        raw_output_json={
            "verdict": "approve", "ai_confidence": 88,
            "reasoning_summary": "Pharmacy covered; documents consistent; within limits.",
            "flags": [],
            "policy_citations": ["Basic Care covers pharmacy", "Pharmacy sub-limit 25,000"],
            "customer_message": "Your pharmacy claim is approved. After your 20% co-pay the covered amount will be processed.",
        },
        created_at=now - timedelta(days=1),
    )
    db.add(rev3)
    db.flush()
    _seed_agent_runs(db, c3.id, rev3.id, {
        "registration": {"registered": True, "reference": f"PA-{c3.id}",
                         "summary": "Monthly diabetes medication pharmacy claim for Ravi Sharma.",
                         "issues": []},
        "completeness": {"complete": True, "missing": [],
                         "assessment": "Prescription and itemized bill present and consistent.",
                         "confidence": 92},
        "document_integrity": {"authenticity_verdict": "clear", "risk_score": 8,
                               "identity_match": True,
                               "red_flags": [],
                               "document_checks": [{"document": "Itemized Bill.pdf", "issue": "ok"}],
                               "assessment": "Account holder name Ravi Sharma appears on the prescription and bill; totals match the claimed amount."},
        "coverage": {"covered": True, "within_limit": True, "exclusions_triggered": [],
                     "assessment": "Pharmacy is covered under Basic Care; amount within annual and pharmacy sub-limit.",
                     "citations": ["Basic Care covers pharmacy", "Pharmacy sub-limit 25,000"]},
        "pre_authorization": {"verdict": "approve", "confidence": 88,
                              "reasoning": "Covered category, complete documents, within all limits, no exclusions.",
                              "flags": [], "citations": ["Basic Care covers pharmacy"]},
        "denial": {"customer_message": c3.customer_message, "letter_reference": f"DL-{c3.id}"},
    }, now - timedelta(days=1))
    db.add(AdminAction(claim_id=c3.id, action="approved",
                       reason_text=c3.customer_message, agreed_with_ai=True,
                       created_at=now - timedelta(days=1)))
    db.add_all([
        ClaimEvent(claim_id=c3.id, status="submitted", note="Claim submitted",
                   created_at=now - timedelta(days=6)),
        ClaimEvent(claim_id=c3.id, status="under_review", note="AI review run by admin",
                   created_at=now - timedelta(days=2)),
        ClaimEvent(claim_id=c3.id, status="approved", note="Claim approved",
                   created_at=now - timedelta(days=1)),
    ])

    db.commit()
    print("[seed] Demo data created: 3 plans, 2 customers, 3 claims.")
