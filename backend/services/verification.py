"""Document verification: LLM extraction + deterministic validation.

Split of responsibility, per the pipeline contract:
  PART 1  extraction  -> the model (prompts/agents/extraction.txt). Perceptual work:
                         transcription, ambiguous-character flagging, tamper signals.
  PART 2  validation  -> services.gstin. Exact arithmetic. Never the model.
  PART 3  envelope    -> assembled here.

The model is never asked whether a GSTIN is valid, and any validity field it
volunteers is discarded — `_verify_extraction` recomputes it from the raw string.
This keeps denials auditable: the reason on a rejected claim traces to a specific
deterministic check, not to a model's opinion.
"""
from __future__ import annotations

from typing import Optional

from services.documents import extract_document
from services.gstin import state_name, validate_gstin
from services.llm_client import LLMError, chat_json
from config import BASE_DIR

_PROMPT = BASE_DIR / "prompts" / "agents" / "extraction.txt"

_DOC_TYPES = {"prescription", "invoice", "pharmacy_bill", "id_proof", "other"}

_FIELDS = (
    "provider_name", "invoice_number", "invoice_date",
    "patient_name", "amount", "diagnosis_or_medicine",
)


def _clamp_conf(v) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def _field(raw: dict, key: str, numeric: bool = False) -> dict:
    """Normalize one {"v":..,"c":..} block into the output contract."""
    block = raw.get(key) or {}
    if not isinstance(block, dict):
        block = {}
    value = block.get("v", block.get("value"))
    if value in ("", "null", "N/A"):
        value = None
    if numeric and value is not None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = None
    return {
        "value": value,
        "confidence": _clamp_conf(block.get("c", block.get("confidence"))),
    }


def _ambiguous(raw_gstin: dict) -> tuple[list[dict], bool]:
    """Normalize the model's ambiguous-character list.

    Returns (entries, had_malformed). Malformed entries are dropped from the
    output — a bogus index is not usable — but `had_malformed` is propagated so
    the caller can still mark the read low-confidence. The model saying "some
    character here was ambiguous" is a caution signal even when it fumbles the
    index, and silently discarding it would upgrade an uncertain read to a clean
    one.
    """
    out = []
    malformed = False
    for item in raw_gstin.get("amb") or raw_gstin.get("ambiguous_chars") or []:
        if not isinstance(item, dict):
            malformed = True
            continue
        pos = item.get("pos", item.get("position"))
        cands = item.get("cand", item.get("candidates")) or []
        try:
            pos = int(pos)
        except (TypeError, ValueError):
            malformed = True
            continue
        if not 0 <= pos < 15:
            malformed = True
            continue
        out.append({"position": pos, "candidates": [str(c) for c in cands]})
    return out, malformed


def verify_extraction(raw: dict) -> dict:
    """Turn a raw extraction-agent response into the validated PART 3 envelope.

    Pure function — no I/O, no LLM. Safe to unit-test and to re-run over stored
    extractions if the validation rules ever change.
    """
    raw = raw or {}
    fields_in = raw.get("f") or raw.get("fields") or {}

    dtype = str(raw.get("dtype") or raw.get("document_type") or "other").lower().strip()
    if dtype not in _DOC_TYPES:
        dtype = "other"

    gstin_raw = fields_in.get("gstin") or {}
    if not isinstance(gstin_raw, dict):
        gstin_raw = {}
    gstin_value = gstin_raw.get("v", gstin_raw.get("value"))
    if gstin_value in ("", "null", "N/A"):
        gstin_value = None
    if gstin_value is not None:
        gstin_value = str(gstin_value)

    ambiguous, had_malformed_amb = _ambiguous(gstin_raw)

    # Deterministic. Anything the model said about validity is ignored.
    verdict = validate_gstin(gstin_value, [a["position"] for a in ambiguous])
    if had_malformed_amb and verdict["gstin_valid"]:
        verdict["gstin_valid_but_low_confidence"] = True

    fields_out = {name: _field(fields_in, name, numeric=(name == "amount"))
                  for name in _FIELDS}
    fields_out["gstin"] = {
        "value": gstin_value,
        "confidence": _clamp_conf(gstin_raw.get("c", gstin_raw.get("confidence"))),
        "ambiguous_chars": ambiguous,
        "gstin_valid": verdict["gstin_valid"],
        "gstin_valid_but_low_confidence": verdict["gstin_valid_but_low_confidence"],
        "reason": verdict["reason"],
        "expected_checksum_char": verdict["expected_checksum_char"],
        "state": state_name(gstin_value[:2]) if gstin_value and len(gstin_value) >= 2 else None,
    }

    notes = raw.get("tnotes", raw.get("tamper_notes"))
    return {
        "document_type": dtype,
        "fields": fields_out,
        "tamper_flag": bool(raw.get("tamper", raw.get("tamper_flag", False))),
        "tamper_notes": str(notes) if notes else None,
        "overall_extraction_confidence": _clamp_conf(
            raw.get("oconf", raw.get("overall_extraction_confidence"))
        ),
    }


def verify_document(path: str, filename: str) -> dict:
    """Full path: read the document, extract with the LLM, validate in code.

    Raises LLMError if the extraction call fails. If the document cannot be read
    at all (no OCR, unsupported type), returns an all-null envelope rather than
    calling the model on nothing.
    """
    info = extract_document(path, filename)
    if info["unverifiable"] or not (info["text"] or "").strip():
        return _empty_envelope(unreadable=True)

    text = info["text"]
    if info["source"] in ("ocr_pdf", "ocr_image") and info["ocr_confidence"] is not None:
        header = (
            f"[Source: OCR, engine confidence {info['ocr_confidence']:.2f}. "
            "Cap field confidence accordingly.]\n"
        )
    else:
        header = "[Source: embedded PDF text, no OCR uncertainty.]\n"

    raw = chat_json(_PROMPT.read_text(encoding="utf-8"), header + text)
    envelope = verify_extraction(raw)
    envelope["source"] = info["source"]
    envelope["ocr_confidence"] = info["ocr_confidence"]
    return envelope


def _empty_envelope(unreadable: bool = False) -> dict:
    fields = {name: {"value": None, "confidence": 0} for name in _FIELDS}
    fields["gstin"] = {
        "value": None, "confidence": 0, "ambiguous_chars": [],
        "gstin_valid": False, "gstin_valid_but_low_confidence": False,
        "reason": None, "expected_checksum_char": None, "state": None,
    }
    return {
        "document_type": "other",
        "fields": fields,
        "tamper_flag": False,
        "tamper_notes": "document could not be read" if unreadable else None,
        "overall_extraction_confidence": 0,
        "source": "none",
        "ocr_confidence": None,
    }
