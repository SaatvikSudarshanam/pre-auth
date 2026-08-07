"""Orchestrates document verification for a claim, with caching and reuse lookup.

One entry point, `verify_claim_documents`, which:
  1. reuses any cached per-document envelope (a document is immutable once
     uploaded, so re-reviewing a claim must not pay for extraction again),
  2. runs services.verification on anything not yet verified,
  3. persists the envelope and the content hash back onto the Document row,
  4. runs the deterministic cross-checks in services.crosscheck against the
     account holder and the claim.

Failure policy: if the extraction LLM is down, verification degrades to
forensics-only rather than aborting the review. Provenance is deterministic and
still worth having, and the resulting checks come back "unknown" — which the
scoring layer already treats as strictly worse than a pass. The alternative,
letting an LLM outage block adjudication entirely, is the more expensive failure.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from models import Claim, Document, utcnow
from services import forensics
from services.crosscheck import run_all
from services.llm_client import LLMError
from services.verification import empty_envelope, verify_document


def _duplicate_lookup(db: Session, claim_id: int):
    """Find other claims that already carry a byte-identical document.

    Scoped to *other* claims — the same file appearing twice within one claim is
    a separate finding (services.crosscheck.check_reuse handles it), and matching
    a document against itself would flag every claim. Not scoped to this user:
    the same forged invoice showing up under two accounts is the strongest fraud
    signal available here, and missing it to preserve tenancy tidiness would be
    the wrong trade.
    """
    def lookup(digest: str) -> list[int]:
        if not digest:
            return []
        rows = (
            db.query(Document.claim_id)
            .filter(Document.sha256 == digest, Document.claim_id != claim_id)
            .distinct()
            .all()
        )
        return [r[0] for r in rows]

    return lookup


def _verify_one(doc: Document, refresh: bool) -> tuple[dict, bool]:
    """Return (envelope, is_new). Reuses the cached envelope unless refreshing."""
    if not refresh and doc.verification_json:
        return doc.verification_json, False

    try:
        return verify_document(doc.path, doc.filename), True
    except LLMError as exc:
        # Degrade to forensics-only. The envelope's fields stay null, so every
        # content cross-check reports "unknown" rather than passing by default.
        art = forensics.analyze(doc.path, doc.filename)
        art = forensics.finalize(art, art["signals"] + [{
            "code": "extraction_unavailable", "severity": "medium",
            "detail": f"Field extraction did not run ({exc}); only file "
                      "provenance was checked",
        }])
        envelope = empty_envelope(unreadable=False)
        envelope["forensics"] = art
        envelope["extraction_error"] = str(exc)
        return envelope, True


def verify_claim_documents(
    db: Session,
    claim: Claim,
    refresh: bool = False,
) -> dict:
    """Verify every document on a claim and cross-check it against the account.

    Set `refresh=True` to re-run extraction even where a cached envelope exists —
    used when the extraction prompt or the validation rules change.
    """
    if not claim.documents:
        return {
            "verdict": "review", "risk": 30,
            "counts": {"pass": 0, "fail": 0, "warn": 0, "unknown": 0},
            "failed_checks": [], "blocking_reasons": [],
            "checks": [], "documents": [],
            "note": "No documents attached — nothing could be verified.",
        }

    pairs: list[tuple[Document, dict]] = []
    dirty = False
    for doc in claim.documents:
        envelope, is_new = _verify_one(doc, refresh)
        if is_new:
            doc.verification_json = envelope
            doc.sha256 = (envelope.get("forensics") or {}).get("sha256")
            doc.verified_at = utcnow()
            dirty = True
        pairs.append((doc, envelope))

    # Hashes must be committed before the reuse lookup runs, or a document
    # verified in this very pass is invisible to the cross-claim query.
    if dirty:
        db.commit()

    return run_all(
        claim, pairs,
        duplicate_lookup=_duplicate_lookup(db, claim.id),
    )


def summarize_for_agent(result: dict, max_documents: int = 6) -> dict:
    """Compact projection of the verification result for the LLM context.

    The full result carries every extracted field and every forensics signal —
    far more than the integrity agent needs, and the largest block in its prompt.
    This keeps the verdict, the failures, and one line per document, which is
    what the agent actually reasons over. The deterministic verdict is already
    authoritative; the agent's job is narrative, not recomputation.
    """
    docs = []
    for d in (result.get("documents") or [])[:max_documents]:
        failures = [
            {"check": c["key"], "status": c["status"], "why": c["detail"]}
            for c in d.get("checks", [])
            if c["status"] in ("fail", "warn")
        ]
        docs.append({
            "file": d["filename"],
            "type": d["doc_type"],
            "forensics": (d.get("forensics") or {}).get("verdict"),
            "issues": failures or None,
        })

    claim_level = [
        {"check": c["key"], "status": c["status"], "why": c["detail"]}
        for c in (result.get("checks") or [])
        if c.get("document") is None and c["status"] in ("fail", "warn", "unknown")
    ]

    return {
        "verdict": result.get("verdict"),
        "risk": result.get("risk"),
        "counts": result.get("counts"),
        "failed_checks": result.get("failed_checks"),
        "blocking_reasons": result.get("blocking_reasons") or None,
        "claim_level": claim_level or None,
        "documents": docs,
        "truncated": len(result.get("documents") or []) > max_documents or None,
    }
