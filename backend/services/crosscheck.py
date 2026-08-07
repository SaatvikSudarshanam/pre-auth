"""Deterministic cross-checks: does the document agree with the account and the claim?

Extraction (services.verification) reads values *off* a document without ever
being told what they should be. This module is the other half: it holds the
authoritative values — the name on the Google account, the hospital typed on the
claim, the amount, the date — and compares them. Keeping the two apart is what
stops the model from being able to talk itself into a match.

Every check returns the same shape so the admin UI can render them uniformly and
a denial can cite one by key:

    {key, label, status, severity, detail, document}

status ∈ pass | fail | warn | unknown
  pass    — the check ran and the values agree
  fail    — the check ran and they disagree
  warn    — ran, disagreement is within the range a legitimate document reaches
  unknown — could not run (field absent, document unreadable). Never a pass.

`unknown` existing as a distinct state is the point of the design. A blank
document must not score the same as a clean one.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Callable, Iterable, Optional

from services.address import validate_address
from services.matching import match_org_name, match_person_name

# Which document types carry a payable amount. A prescription or a discharge
# summary legitimately has none, so absence there is not a finding.
_BILLING_DOC_TYPES = {"itemized_bill", "invoice", "pharmacy_bill"}

# Document types a hospital stamps or signs before handing over. An ID proof
# carries its own security features instead, and "other" is unconstrained — an
# unstamped one of those is only worth a note.
_STAMPED_DOC_TYPES = {"itemized_bill", "invoice", "pharmacy_bill",
                      "prescription", "discharge_summary", "lab_report"}

# Severity → risk contribution, mirroring services.forensics so the two can be
# folded into one score.
_WEIGHT = {"critical": 100, "high": 45, "medium": 20, "low": 8, "info": 0}

# Amounts: claiming *more* than the documents show is the fraud direction, so
# the tolerance is asymmetric. Claiming less is conservative and only noted.
_OVERCLAIM_TOLERANCE = 1.02
_UNDERCLAIM_NOTICE = 0.60

# Invoice dates this far from the stated service date stop being a rounding
# difference and start being a different episode of care.
_DATE_DRIFT_WARN_DAYS = 30
_DATE_DRIFT_FAIL_DAYS = 120

# Extraction confidence at or above which a read counts as "clean" — the point
# where a failed checksum stops being explainable as a misread character.
_CONFIDENT_READ = 80

_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y",
    "%d-%m-%y", "%d/%m/%y", "%Y/%m/%d",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
    "%d-%b-%Y", "%d-%B-%Y", "%d %b %y",
)


def _check(key, label, status, severity, detail, document=None) -> dict:
    return {"key": key, "label": label, "status": status, "severity": severity,
            "detail": detail, "document": document}


def parse_date(value: Optional[str]) -> Optional[date]:
    """Best-effort date parse over the formats Indian invoices actually use.

    Ambiguous DD/MM vs MM/DD is resolved toward DD/MM (the local convention);
    where the day exceeds 12 the format is unambiguous anyway. Returns None
    rather than guessing when nothing parses — a wrong date silently fails a
    consistency check against a real document.
    """
    if not value:
        return None
    text = str(value).strip()
    # Strip an ordinal suffix ("1st Jan 2026") which strptime cannot read.
    text = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", text, flags=re.I).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _value(envelope: dict, field: str):
    return ((envelope.get("fields") or {}).get(field) or {}).get("value")


def _confidence(envelope: dict, field: str) -> int:
    return ((envelope.get("fields") or {}).get(field) or {}).get("confidence") or 0


# ---- individual checks ---------------------------------------------------
def check_patient_name(envelope: dict, account_name: str, filename: str) -> dict:
    """Does the patient named on the document correspond to the logged-in account?"""
    doc_name = _value(envelope, "patient_name")
    if not account_name:
        return _check("patient_name", "Patient name matches account", "unknown",
                      "medium", "Account has no full name on file", filename)
    if not doc_name:
        return _check("patient_name", "Patient name matches account", "unknown",
                      "medium", "No patient name could be read from this document",
                      filename)

    result = match_person_name(account_name, doc_name)
    status = {"match": "pass", "partial": "warn",
              "mismatch": "fail", "unknown": "unknown"}[result["status"]]
    severity = "critical" if status == "fail" else "medium"
    detail = f"Document says {doc_name!r}, account is {account_name!r} — {result['detail']}"
    return _check("patient_name", "Patient name matches account", status,
                  severity, detail, filename)


def check_provider(envelope: dict, claim_provider: str, filename: str) -> dict:
    """Does the issuing hospital on the document match the one typed on the claim?"""
    doc_provider = _value(envelope, "provider_name")
    if not claim_provider:
        return _check("provider_name", "Hospital matches the claim", "unknown",
                      "medium", "Claim has no provider name", filename)
    if not doc_provider:
        return _check("provider_name", "Hospital matches the claim", "unknown",
                      "medium", "No provider name could be read from this document",
                      filename)

    result = match_org_name(claim_provider, doc_provider)
    status = {"match": "pass", "partial": "warn",
              "mismatch": "fail", "unknown": "unknown"}[result["status"]]
    severity = "high" if status == "fail" else "medium"
    return _check("provider_name", "Hospital matches the claim", status,
                  severity, result["detail"], filename)


def check_gstin(envelope: dict, filename: str) -> dict:
    """GSTIN checksum — recomputed here, never taken from the model."""
    g = (envelope.get("fields") or {}).get("gstin") or {}
    value = g.get("value")
    if not value:
        return _check("gstin", "GSTIN valid", "unknown", "low",
                      "No GSTIN printed on this document", filename)
    if g.get("gstin_valid"):
        note = f"{value} passed format, state-code, PAN and mod-36 checksum"
        if g.get("gstin_valid_but_low_confidence"):
            amb = g.get("ambiguous_chars") or []
            positions = ", ".join(str(a.get("position")) for a in amb) or "unspecified"
            return _check("gstin", "GSTIN valid", "warn", "medium",
                          f"{note}, but character(s) at position {positions} were "
                          "visually ambiguous — the checksum was computed over a "
                          "reading we are not certain of", filename)
        return _check("gstin", "GSTIN valid", "pass", "low", note, filename)

    reason = g.get("reason") or "unreadable"
    expected = g.get("expected_checksum_char")
    detail = f"{value} failed validation ({reason})"

    # A checksum mismatch is the fabrication signature: the number is correctly
    # shaped in every other respect and only the check digit is wrong, which is
    # what happens when someone invents a plausible-looking GSTIN. It escalates
    # to critical only on a *confident* read, though — a single misread character
    # produces exactly the same failure, so an ambiguous or low-confidence
    # transcription is not evidence of anything and stays at "high".
    if reason == "checksum_mismatch":
        ambiguous = g.get("ambiguous_chars") or []
        confident = not ambiguous and (g.get("confidence") or 0) >= _CONFIDENT_READ
        if expected:
            detail += f" — the check character should be {expected!r}"
        if confident:
            return _check("gstin", "GSTIN valid", "fail", "critical",
                          detail + ". The number is well-formed but the check digit "
                          "is wrong, and it was read cleanly — this is a fabricated "
                          "GSTIN, not a transcription error", filename)
        detail += (". The read was not clean enough to distinguish a fabricated "
                   "number from a misread one — verify against the original")

    return _check("gstin", "GSTIN valid", "fail", "high", detail, filename)


def check_address(envelope: dict, filename: str) -> dict:
    """Address plausibility and PIN ↔ GSTIN-state agreement."""
    g = (envelope.get("fields") or {}).get("gstin") or {}
    result = validate_address(_value(envelope, "provider_address"), g.get("state"))

    if result["status"] == "missing":
        return _check("address", "Provider address plausible", "unknown", "medium",
                      "No provider address printed on this document", filename)
    if result["status"] == "suspect":
        severity = "high" if result["state_match"] is False else "medium"
        return _check("address", "Provider address plausible", "fail", severity,
                      result["detail"], filename)
    detail = result["detail"]
    if result["pin"]:
        detail = (f"PIN {result['pin']}"
                  + (f" ({'/'.join(result['pin_states'])})" if result["pin_states"] else "")
                  + (f", consistent with the GSTIN state {result['gstin_state']}"
                     if result["state_match"] else "")
                  + (f". {result['detail']}" if result["issues"] else ""))
    status = "warn" if result["issues"] else "pass"
    return _check("address", "Provider address plausible", status, "low",
                  detail, filename)


def check_artifact(envelope: dict, filename: str) -> dict:
    """File provenance — watermarks, generator metadata, EXIF, recompression."""
    art = envelope.get("forensics") or {}
    verdict = art.get("verdict")
    signals = art.get("signals") or []
    worst = [s for s in signals if s["severity"] in ("critical", "high")]
    summary = "; ".join(s["detail"] for s in worst) if worst else None

    if verdict == "synthetic_suspected":
        return _check("artifact", "File is a genuine document", "fail", "critical",
                      summary or "File provenance indicates it was generated, not issued",
                      filename)
    if verdict == "review":
        return _check("artifact", "File is a genuine document", "warn", "medium",
                      summary or "; ".join(s["detail"] for s in signals[:2])
                      or "Provenance is unusual", filename)
    if verdict == "unknown" or not verdict:
        return _check("artifact", "File is a genuine document", "unknown", "medium",
                      "File provenance could not be established", filename)
    return _check("artifact", "File is a genuine document", "pass", "low",
                  "No watermark, editor metadata, or generation markers found",
                  filename)


def check_watermark(envelope: dict, filename: str) -> dict:
    """Specimen/template watermark on the page — reported separately from forensics.

    Called out as its own check because it is the single most legible reason to
    refuse a document: "this says SPECIMEN across it" needs no further argument.
    """
    art = envelope.get("forensics") or {}
    terms = art.get("watermark_terms") or []
    model_text = envelope.get("watermark_text")

    if terms:
        return _check("watermark", "No specimen/template watermark", "fail",
                      "critical",
                      f"Page carries template wording: {', '.join(terms[:5])}",
                      filename)
    if model_text:
        return _check("watermark", "No specimen/template watermark", "warn",
                      "medium",
                      f"A watermark is visible ({model_text!r}); it does not match "
                      "known specimen wording", filename)
    return _check("watermark", "No specimen/template watermark", "pass", "low",
                  "No watermark text detected", filename)


def check_stamp(envelope: dict, doc_type: str, filename: str) -> dict:
    """Is the document stamped, sealed, or signed?

    A hospital bill, prescription, or discharge summary passes through a counter
    where somebody stamps it. A page that was printed (or generated) and never
    physically handled carries no stamp, no seal, and no signature — which is
    what a fabricated document looks like.

    Two independent observers: services.forensics counts coloured stamp-pad and
    pen ink in the pixels; the extraction agent reports what it can see, which
    catches black-ink stamps the colour test cannot. Either one suffices.

    Exempt: a document declaring itself computer-generated, or one carrying a
    digital signature. Both are legitimate and common, and failing them would
    flag the most professionally-issued documents in the set.
    """
    label = "Document is stamped or signed"
    expected = doc_type in _STAMPED_DOC_TYPES or \
        envelope.get("document_type") in _STAMPED_DOC_TYPES

    art = envelope.get("forensics") or {}
    seal = envelope.get("seal") or {}
    detected = (art.get("seal") or {}).get("found")
    reported = seal.get("present")

    if art.get("digitally_signed"):
        return _check("stamp", label, "pass", "low",
                      "Carries a digital signature, which supersedes a physical "
                      "stamp", filename)
    if seal.get("computer_generated") or art.get("computer_generated"):
        return _check("stamp", label, "pass", "low",
                      "Declares itself computer-generated — no stamp expected",
                      filename)

    if detected or reported:
        parts = []
        if reported:
            kind = seal.get("kind") or "stamp"
            parts.append(f"{kind} visible" + (f" reading {seal['text']!r}"
                                              if seal.get("text") else ""))
        if detected:
            ink = art["seal"]
            parts.append(f"{ink.get('dominant_hue') or 'coloured'} ink over "
                         f"{ink['ink_ratio'] * 100:.2f}% of the page")
        return _check("stamp", label, "pass", "low", "; ".join(parts), filename)

    if detected is None and reported is None:
        return _check("stamp", label, "unknown", "medium",
                      "Could not determine whether the document is stamped",
                      filename)

    if not expected:
        return _check("stamp", label, "warn", "low",
                      f"No stamp, seal, or signature found — not normally "
                      f"required on a {doc_type.replace('_', ' ')}", filename)

    return _check("stamp", label, "fail", "medium",
                  f"No stamp, seal, or signature anywhere on this "
                  f"{doc_type.replace('_', ' ')}, and it does not declare itself "
                  "computer-generated — a document issued at a billing counter "
                  "is stamped there", filename)


def check_amounts(envelopes: Iterable[dict], claim_amount: float) -> dict:
    """Claimed amount against the total actually documented."""
    amounts = []
    for env, doc_type in envelopes:
        if doc_type not in _BILLING_DOC_TYPES and env.get("document_type") not in _BILLING_DOC_TYPES:
            continue
        value = _value(env, "amount")
        if isinstance(value, (int, float)) and value > 0:
            amounts.append(float(value))

    if not amounts:
        return _check("amount", "Claimed amount is documented", "unknown", "medium",
                      "No amount could be read from any billing document")

    documented = sum(amounts)
    claimed = float(claim_amount or 0)
    parts = " + ".join(f"{a:,.0f}" for a in amounts)

    if claimed > documented * _OVERCLAIM_TOLERANCE:
        excess = claimed - documented
        return _check("amount", "Claimed amount is documented", "fail", "high",
                      f"Claim is {claimed:,.0f} but the documents total {documented:,.0f} "
                      f"({parts}) — {excess:,.0f} more is being claimed than billed")
    if claimed < documented * _UNDERCLAIM_NOTICE:
        return _check("amount", "Claimed amount is documented", "warn", "low",
                      f"Claim of {claimed:,.0f} is well below the documented "
                      f"{documented:,.0f} ({parts}) — verify the right bills are attached")
    return _check("amount", "Claimed amount is documented", "pass", "low",
                  f"Claim {claimed:,.0f} is covered by documents totalling "
                  f"{documented:,.0f} ({parts})")


def check_dates(envelopes: Iterable[dict], service_date: Optional[str],
                today: Optional[date] = None) -> dict:
    """Invoice dates against the stated date of service."""
    today = today or date.today()
    service = parse_date(service_date)
    parsed = []
    for env, filename in envelopes:
        d = parse_date(_value(env, "invoice_date"))
        if d:
            parsed.append((d, filename))

    if not parsed:
        return _check("dates", "Document dates are consistent", "unknown", "low",
                      "No invoice date could be read from any document")

    future = [(d, f) for d, f in parsed if d > today]
    if future:
        listed = ", ".join(f"{f} ({d.isoformat()})" for d, f in future[:3])
        return _check("dates", "Document dates are consistent", "fail", "high",
                      f"Document dated in the future: {listed}")

    if not service:
        return _check("dates", "Document dates are consistent", "unknown", "low",
                      "Claim has no date of service to compare against")

    drifts = [(abs((d - service).days), d, f) for d, f in parsed]
    worst_days, worst_date, worst_file = max(drifts)
    if worst_days > _DATE_DRIFT_FAIL_DAYS:
        return _check("dates", "Document dates are consistent", "fail", "high",
                      f"{worst_file} is dated {worst_date.isoformat()}, {worst_days} days "
                      f"from the stated service date {service.isoformat()} — this is a "
                      "different episode of care")
    if worst_days > _DATE_DRIFT_WARN_DAYS:
        return _check("dates", "Document dates are consistent", "warn", "medium",
                      f"{worst_file} is dated {worst_date.isoformat()}, {worst_days} days "
                      f"from the stated service date {service.isoformat()}")
    return _check("dates", "Document dates are consistent", "pass", "low",
                  f"All {len(parsed)} dated document(s) fall within {worst_days} day(s) "
                  f"of the service date {service.isoformat()}")


def check_reuse(hashes: list[tuple[str, str]],
                lookup: Optional[Callable[[str], list]] = None) -> dict:
    """Has this exact file already been submitted — here or on another claim?

    Exact-hash only. A re-photographed or re-saved bill will not collide, so this
    is a floor on reuse detection, not a ceiling — but a collision is conclusive,
    which is what makes it worth checking before anything fuzzier.
    """
    seen: dict[str, list[str]] = {}
    for digest, filename in hashes:
        if digest:
            seen.setdefault(digest, []).append(filename)

    internal = {d: names for d, names in seen.items() if len(names) > 1}
    if internal:
        dupes = "; ".join(", ".join(n) for n in internal.values())
        return _check("reuse", "Documents are not reused", "fail", "high",
                      f"The same file was uploaded more than once on this claim: {dupes}")

    if lookup:
        for digest, names in seen.items():
            others = lookup(digest)
            if others:
                where = ", ".join(str(o) for o in others[:3])
                # Deliberately not phrased as "already submitted" — the lookup is
                # symmetric, so both claims in a collision raise this, and which
                # one came first is not something this check establishes.
                return _check("reuse", "Documents are not reused", "fail", "critical",
                              f"{names[0]} is byte-identical to a document on "
                              f"claim(s) {where} — the same file has been submitted "
                              "against more than one claim")

    if not seen:
        return _check("reuse", "Documents are not reused", "unknown", "low",
                      "No file hashes available")
    return _check("reuse", "Documents are not reused", "pass", "low",
                  f"All {len(seen)} document(s) are unique across submitted claims")


# ---- aggregation ---------------------------------------------------------
def run_all(
    claim,
    documents: list[tuple],
    duplicate_lookup: Optional[Callable[[str], list]] = None,
    today: Optional[date] = None,
) -> dict:
    """Run every cross-check over a claim's verified documents.

    `documents` is a list of (Document, envelope) pairs, where envelope comes
    from services.verification.verify_document.
    """
    account_name = (claim.user.full_name or "") if claim.user else ""
    checks: list[dict] = []
    per_document: list[dict] = []

    for doc, env in documents:
        doc_checks = [
            check_patient_name(env, account_name, doc.filename),
            check_provider(env, claim.provider_name, doc.filename),
            check_gstin(env, doc.filename),
            check_address(env, doc.filename),
            check_stamp(env, doc.doc_type, doc.filename),
            check_watermark(env, doc.filename),
            check_artifact(env, doc.filename),
        ]
        checks.extend(doc_checks)
        art = env.get("forensics") or {}
        per_document.append({
            "document_id": doc.id,
            "filename": doc.filename,
            "doc_type": doc.doc_type,
            "document_type_read": env.get("document_type"),
            "source": env.get("source"),
            "ocr_confidence": env.get("ocr_confidence"),
            "extraction_confidence": env.get("overall_extraction_confidence"),
            "fields": env.get("fields"),
            "forensics": {
                "verdict": art.get("verdict"),
                "risk": art.get("risk"),
                "generator": art.get("generator"),
                "signals": art.get("signals"),
                "sha256": art.get("sha256"),
            },
            "checks": doc_checks,
        })

    checks.append(check_amounts(
        [(env, doc.doc_type) for doc, env in documents], claim.amount))
    checks.append(check_dates(
        [(env, doc.filename) for doc, env in documents],
        claim.date_of_service, today=today))
    checks.append(check_reuse(
        [((env.get("forensics") or {}).get("sha256"), doc.filename)
         for doc, env in documents],
        duplicate_lookup))

    return {**summarize(checks), "checks": checks, "documents": per_document}


def summarize(checks: list[dict]) -> dict:
    """Roll a check list into a verdict and a 0-100 risk score.

    Risk is the strongest failure plus a halved contribution from the rest, so
    several medium findings can escalate into a review without ever outranking a
    single critical one. Warns count at a quarter — real enough to move the
    number, not enough to fail a claim on their own.
    """
    failed = [c for c in checks if c["status"] == "fail"]
    warned = [c for c in checks if c["status"] == "warn"]
    unknown = [c for c in checks if c["status"] == "unknown"]
    passed = [c for c in checks if c["status"] == "pass"]

    weights = sorted((_WEIGHT.get(c["severity"], 0) for c in failed), reverse=True)
    risk = (weights[0] + sum(w // 2 for w in weights[1:])) if weights else 0
    risk += sum(_WEIGHT.get(c["severity"], 0) // 4 for c in warned)
    # An unknown is not a pass, but it is not evidence of fraud either — it costs
    # a little so a blank document cannot post a perfect score.
    risk += 5 * len(unknown)
    risk = max(0, min(100, risk))

    critical = [c for c in failed if c["severity"] == "critical"]
    if critical:
        verdict = "suspected_fraud"
    elif failed or risk >= 45:
        verdict = "review"
    elif unknown and len(unknown) >= len(passed):
        # Nothing failed, but at least half of what we tried to check could not
        # be checked. That is a document set we have no basis to clear, and it
        # is exactly what a blank or unreadable upload produces.
        verdict = "review"
    else:
        verdict = "clear"

    return {
        "verdict": verdict,
        "risk": risk,
        "counts": {"pass": len(passed), "fail": len(failed),
                   "warn": len(warned), "unknown": len(unknown)},
        "failed_checks": [c["key"] for c in failed],
        "blocking_reasons": [c["detail"] for c in critical],
    }
