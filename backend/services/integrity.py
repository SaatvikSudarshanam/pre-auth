"""Deterministic document-integrity / identity cross-check (OCR-backed).

This is a NON-LLM signal (the LLM agent adds narrative on top). It reads the text
out of each submitted document — using OCR for images and scanned PDFs — and checks
whether the account holder's name (the identity the session is logged in as) appears
in the readable documents (ID proof, bills, etc.). If none of the readable documents
carry the claimant's name, that is a hard identity mismatch used to block approval.

An OCR match score summarizes how confidently the identity was read/matched from
OCR'd documents.
"""
import re
from typing import List

from models import Claim
from services.documents import extract_document


def _name_tokens(name: str) -> List[str]:
    return [t for t in re.split(r"[^a-z]+", (name or "").lower()) if len(t) >= 3]


def check_identity(claim: Claim) -> dict:
    user = claim.user
    account_name = user.full_name or ""
    tokens = _name_tokens(account_name)

    per_doc = []
    verifiable: List[str] = []
    unverifiable: List[str] = []
    name_found: List[str] = []
    missing_name: List[str] = []
    ocr_confidences: List[float] = []      # confidences of OCR'd docs
    ocr_match_confidences: List[float] = []  # confidences of OCR'd docs that matched the name
    ocr_used = False

    for d in claim.documents:
        info = extract_document(d.path, d.filename)
        low = (info["text"] or "").lower()
        is_ocr = info["source"] in ("ocr_pdf", "ocr_image")
        conf = info.get("ocr_confidence")
        if is_ocr and conf is not None:
            ocr_used = True
            ocr_confidences.append(float(conf))

        if info["unverifiable"]:
            unverifiable.append(d.filename)
            per_doc.append({
                "document": d.filename, "doc_type": d.doc_type, "source": info["source"],
                "verifiable": False, "name_present": None, "ocr_confidence": conf,
            })
            continue

        verifiable.append(d.filename)
        present = bool(tokens) and any(tok in low for tok in tokens)
        per_doc.append({
            "document": d.filename, "doc_type": d.doc_type, "source": info["source"],
            "verifiable": True, "name_present": present, "ocr_confidence": conf,
        })
        if present:
            name_found.append(d.filename)
            if is_ocr and conf is not None:
                ocr_match_confidences.append(float(conf))
        else:
            missing_name.append(d.filename)

    hard_mismatch = len(verifiable) > 0 and len(name_found) == 0
    id_proof_mismatch = any(
        pd["doc_type"] == "id_proof" and pd["verifiable"] and pd["name_present"] is False
        for pd in per_doc
    )

    # OCR match score (0-100): mean confidence of OCR'd documents where the account
    # name was found. If OCR was used but nothing matched, the score is 0. If no OCR
    # was needed (all embedded-text PDFs), it's None.
    if not ocr_used:
        ocr_score = None
    elif ocr_match_confidences:
        ocr_score = round(100 * sum(ocr_match_confidences) / len(ocr_match_confidences))
    else:
        ocr_score = 0
    ocr_mean = round(100 * sum(ocr_confidences) / len(ocr_confidences)) if ocr_confidences else None

    return {
        "account_name": account_name,
        "identity_ok": (not hard_mismatch) and (not id_proof_mismatch),
        "hard_mismatch": hard_mismatch or id_proof_mismatch,
        "name_found_documents": name_found,
        "missing_name_documents": missing_name,
        "unverifiable_documents": unverifiable,
        "id_proof_mismatch": id_proof_mismatch,
        "ocr_used": ocr_used,
        "ocr_score": ocr_score,            # name-match confidence from OCR
        "ocr_mean_confidence": ocr_mean,   # overall OCR read confidence
        "per_document": per_doc,
    }
