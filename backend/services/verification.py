"""Per-document verification: forensics + LLM extraction + deterministic validation.

Split of responsibility, per the pipeline contract:
  PART 0  forensics   -> services.forensics. Provenance of the *file*: hashes,
                         container metadata, EXIF, embedded generator strings,
                         watermark text. No model involved.
  PART 1  extraction  -> the model (prompts/agents/extraction.txt). Perceptual work
                         on the *content*: transcription, ambiguous-character
                         flagging, tamper and synthetic-appearance observations.
  PART 2  validation  -> services.gstin, services.address, services.matching.
                         Exact arithmetic and string comparison. Never the model.
  PART 3  envelope    -> assembled here.

The model is never asked whether a GSTIN is valid, whether an address is real, or
whether a name matches the account holder — it is not even shown the account
holder. Any validity field it volunteers is discarded and recomputed. This keeps
denials auditable: the reason on a rejected claim traces to a specific
deterministic check, not to a model's opinion.
"""
from __future__ import annotations

from config import BASE_DIR
from services import forensics
from services.documents import extract_document
from services.gstin import state_name, validate_gstin
from services.llm_client import LLMError, chat_json

_PROMPT = BASE_DIR / "prompts" / "agents" / "extraction.txt"

_DOC_TYPES = {"prescription", "invoice", "pharmacy_bill", "id_proof", "other"}

# Plain text fields. gstin is handled separately (it carries a verdict block).
_FIELDS = (
    "provider_name", "provider_address", "registration_number", "contact",
    "invoice_number", "invoice_date", "patient_name", "amount",
    "diagnosis_or_medicine",
)

# The extraction agent's own synthetic-appearance score, above which we raise a
# forensics signal. Deliberately high: this is a perceptual judgement from a
# text-only read, so it corroborates container evidence rather than standing
# alone, and it is capped at "high" — never "critical".
_SYNTH_THRESHOLD = 70
_LETTERHEAD_THRESHOLD = 25


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
    elif value is not None:
        value = str(value).strip() or None
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


_SEAL_KINDS = {"seal", "signature", "both", "none"}


def _seal(block) -> dict:
    """Normalize the model's stamp/seal observation.

    A malformed or absent block becomes `present: None` — "the model did not
    tell us" — never `False`. Reading a missing answer as "there is no stamp"
    would manufacture a fraud signal out of the model's silence.
    """
    if not isinstance(block, dict):
        return {"present": None, "kind": None, "text": None, "computer_generated": False}

    present = block.get("p", block.get("present"))
    if not isinstance(present, bool):
        present = None

    kind = str(block.get("k", block.get("kind")) or "").lower().strip()
    if kind not in _SEAL_KINDS:
        kind = None
    # "none" and present=True contradict each other; trust the explicit boolean.
    if kind == "none" and present is None:
        present = False

    text = block.get("t", block.get("text"))
    text = str(text).strip() or None if text else None

    return {
        "present": present,
        "kind": kind,
        "text": text,
        "computer_generated": bool(block.get("cg", block.get("computer_generated"))),
    }


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
    # State is read from the number only when the number itself passed. Deriving
    # a state from a GSTIN we already rejected would feed a downstream
    # cross-check with a value we have no reason to trust.
    gstin_state = (
        state_name(gstin_value[:2])
        if verdict["gstin_valid"] and gstin_value and len(gstin_value) >= 2
        else None
    )
    fields_out["gstin"] = {
        "value": gstin_value,
        "confidence": _clamp_conf(gstin_raw.get("c", gstin_raw.get("confidence"))),
        "ambiguous_chars": ambiguous,
        "gstin_valid": verdict["gstin_valid"],
        "gstin_valid_but_low_confidence": verdict["gstin_valid_but_low_confidence"],
        "reason": verdict["reason"],
        "expected_checksum_char": verdict["expected_checksum_char"],
        "state": gstin_state,
    }

    notes = raw.get("tnotes", raw.get("tamper_notes"))
    watermark = raw.get("wm", raw.get("watermark"))
    snotes = raw.get("snotes", raw.get("synthetic_notes"))
    return {
        "document_type": dtype,
        "fields": fields_out,
        "tamper_flag": bool(raw.get("tamper", raw.get("tamper_flag", False))),
        "tamper_notes": str(notes) if notes else None,
        "watermark_text": str(watermark).strip() or None if watermark else None,
        "seal": _seal(raw.get("seal") or raw.get("stamp")),
        "letterhead_score": _clamp_conf(raw.get("lh", raw.get("letterhead_score"))),
        "synthetic_score": _clamp_conf(raw.get("synth", raw.get("synthetic_score"))),
        "synthetic_notes": str(snotes) if snotes else None,
        "overall_extraction_confidence": _clamp_conf(
            raw.get("oconf", raw.get("overall_extraction_confidence"))
        ),
    }


def _perceptual_signals(envelope: dict) -> list[dict]:
    """Fold the model's perceptual observations into forensics-shaped signals.

    Capped at "high": these come from a text-only read of an OCR transcript, so
    they can corroborate container evidence but must never on their own produce
    the "critical" verdict that refuses a document outright.
    """
    signals: list[dict] = []
    if envelope.get("tamper_flag"):
        signals.append({
            "code": "visual_tamper", "severity": "high",
            "detail": envelope.get("tamper_notes")
                      or "Extraction agent observed tampering artifacts",
        })
    if envelope.get("synthetic_score", 0) >= _SYNTH_THRESHOLD:
        signals.append({
            "code": "synthetic_appearance", "severity": "high",
            "detail": f"Page reads as machine-generated "
                      f"({envelope['synthetic_score']}/100): "
                      + (envelope.get("synthetic_notes") or "no paper/scan artifacts"),
        })
    if envelope.get("letterhead_score", 100) < _LETTERHEAD_THRESHOLD:
        signals.append({
            "code": "weak_letterhead", "severity": "medium",
            "detail": f"Little or no institutional letterhead "
                      f"({envelope['letterhead_score']}/100)",
        })
    return signals


def _seal_overrides(envelope: dict) -> dict:
    """What the model saw that the pixel-level seal check could not.

    Two blind spots the detector has by construction: a stamp inked in black is
    indistinguishable from printed text by colour alone, and a "computer
    generated" note only exists in the text layer. Where the model reports
    either, its observation is merged into the forensics detail so `finalize`
    withdraws the no-stamp finding.

    Only ever *withdraws* a finding. The model saying "no stamp" does not add
    one — the deterministic check already covers that direction, and letting a
    model's negative observation create a fraud signal would put an unverifiable
    judgement into the block path.
    """
    seal = envelope.get("seal") or {}
    out: dict = {}
    if seal.get("computer_generated"):
        out["computer_generated"] = True
    if seal.get("present") is True:
        out["seal_seen_by_model"] = {"kind": seal.get("kind"), "text": seal.get("text")}
    return out


def verify_document(path: str, filename: str) -> dict:
    """Full path: forensics, read the document, extract with the LLM, validate in code.

    Raises LLMError if the extraction call fails. If the document cannot be read
    at all (no OCR, unsupported type), returns an all-null envelope rather than
    calling the model on nothing — but the forensics still run, because a file we
    cannot read is exactly the case where provenance matters most.
    """
    art = forensics.analyze(path, filename)
    info = extract_document(path, filename)

    if info["unverifiable"] or not (info["text"] or "").strip():
        envelope = empty_envelope(unreadable=True)
        art = forensics.finalize(
            art,
            art["signals"] + [{
                "code": "unreadable_content", "severity": "medium",
                "detail": "No text could be extracted — the document cannot be "
                          "cross-checked against the claim",
            }],
        )
        envelope["forensics"] = art
        envelope["source"] = info["source"]
        envelope["ocr_confidence"] = info["ocr_confidence"]
        return envelope

    text = info["text"]
    if info["source"] in ("ocr_pdf", "ocr_image") and info["ocr_confidence"] is not None:
        header = (
            f"[Source: OCR, engine confidence {info['ocr_confidence']:.2f}. "
            "Cap field confidence accordingly.]\n"
        )
        # forensics.analyze only saw the embedded text layer, which a scanned
        # document does not have — rescan the watermark/letterhead heuristics
        # over what OCR actually recovered.
        ocr_scan = forensics.scan_extracted_text(text)
        art = forensics.finalize({**art, **ocr_scan["detail"]},
                                 art["signals"] + ocr_scan["signals"])
    else:
        header = "[Source: embedded PDF text, no OCR uncertainty.]\n"

    raw = chat_json(_PROMPT.read_text(encoding="utf-8"), header + text)
    envelope = verify_extraction(raw)
    envelope["forensics"] = forensics.finalize(
        {**art, **_seal_overrides(envelope)},
        art["signals"] + _perceptual_signals(envelope),
    )
    envelope["source"] = info["source"]
    envelope["ocr_confidence"] = info["ocr_confidence"]
    return envelope


def empty_envelope(unreadable: bool = False) -> dict:
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
        "watermark_text": None,
        # present=None, not False — nobody looked, which is not the same as
        # looking and finding nothing.
        "seal": {"present": None, "kind": None, "text": None,
                 "computer_generated": False},
        "letterhead_score": 0,
        "synthetic_score": 0,
        "synthetic_notes": None,
        "overall_extraction_confidence": 0,
        "forensics": None,
        "source": "none",
        "ocr_confidence": None,
    }
