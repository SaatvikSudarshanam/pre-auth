#!/usr/bin/env python3
"""GSTIN validation verification script.

Run this to verify the deterministic validator is working correctly.
Usage: python verify_gstin.py

Covers the three properties that matter for a claims pipeline:
  1. The checksum matches the published GSTN reference vector.
  2. Every single-character corruption of a valid GSTIN is caught.
  3. A model claiming "gstin_valid": true cannot override the arithmetic.
"""

import random
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent))

from services.gstin import CHARSET, VALID_STATE_CODES, compute_checksum, validate_gstin
from services.verification import verify_extraction

# The canonical example from GSTN documentation; every reference implementation
# of the mod-36 algorithm reproduces this checksum.
REFERENCE_GSTIN = "27AAPFU0939F1ZV"

_passed = 0
_failed = 0


def check(label: str, got, want) -> None:
    global _passed, _failed
    if got == want:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}: expected {want!r}, got {got!r}")


def test_reference_vector() -> None:
    print("\n[1] Reference vector")
    check(f"checksum of {REFERENCE_GSTIN}",
          compute_checksum(REFERENCE_GSTIN[:14]), REFERENCE_GSTIN[14])
    check("validates clean", validate_gstin(REFERENCE_GSTIN)["reason"], "valid")


def test_round_trip(n: int = 3000) -> None:
    print(f"\n[2] Round-trip over {n} generated GSTINs")
    random.seed(7)
    ok = 0
    states = sorted(VALID_STATE_CODES)
    letters = CHARSET[10:]
    for _ in range(n):
        p = random.choice(states)
        p += "".join(random.choice(letters) for _ in range(5))
        p += "".join(random.choice("0123456789") for _ in range(4))
        p += random.choice(letters)
        p += random.choice(CHARSET[1:])
        p += "Z"
        if validate_gstin(p + compute_checksum(p))["gstin_valid"]:
            ok += 1
    check("all computed checksums validate", ok, n)


def test_mutation_sensitivity() -> None:
    print("\n[3] Single-character corruption detection")
    base = REFERENCE_GSTIN
    missed = 0
    total = 0
    for i in range(14):
        for c in CHARSET:
            if c == base[i]:
                continue
            m = base[:i] + c + base[i + 1:]
            # Only count corruptions that still look well-formed — those are the
            # dangerous ones a format-only check would wave through.
            if validate_gstin(m)["reason"] in ("invalid_format", "invalid_state_code",
                                               "invalid_length", "invalid_pan_segment"):
                continue
            total += 1
            if validate_gstin(m)["gstin_valid"]:
                missed += 1
    check(f"format-valid corruptions missed (of {total})", missed, 0)


def test_reason_routing() -> None:
    print("\n[4] Failure reasons stop at the first failing check")
    cases = [
        ("27AAPFU0939F1Z", "invalid_length"),
        ("27AAPFU0939F1QV", "invalid_format"),       # position 13 must be 'Z'
        ("27aapfu0939f1zv", "invalid_format"),       # lowercase is not auto-corrected
        ("99AAPFU0939F1ZV", "invalid_state_code"),
        ("27AAPFU0939F1ZX", "checksum_mismatch"),
        (REFERENCE_GSTIN, "valid"),
        (None, None),
    ]
    for value, want in cases:
        check(f"{value!r}", validate_gstin(value)["reason"], want)


def test_ambiguity_flag() -> None:
    print("\n[5] Ambiguous characters taint an otherwise-clean pass")
    r = validate_gstin(REFERENCE_GSTIN, ambiguous_positions=[9])
    check("still valid", r["gstin_valid"], True)
    check("marked low confidence", r["gstin_valid_but_low_confidence"], True)
    clean = validate_gstin(REFERENCE_GSTIN)
    check("clean read not flagged", clean["gstin_valid_but_low_confidence"], False)


def test_model_cannot_override() -> None:
    print("\n[6] Model-asserted validity is discarded")
    raw = {
        "dtype": "invoice",
        "f": {"gstin": {"v": "27AAPFU0939F1ZX", "c": 88,
                        "gstin_valid": True, "reason": "valid"}},
        "oconf": 88,
    }
    g = verify_extraction(raw)["fields"]["gstin"]
    check("recomputed as invalid", g["gstin_valid"], False)
    check("reason from code", g["reason"], "checksum_mismatch")
    check("expected char surfaced", g["expected_checksum_char"], "V")


def test_malformed_model_output() -> None:
    print("\n[7] Malformed model output degrades safely")
    for label, raw in [
        ("empty response", {}),
        ("gstin not a dict", {"f": {"gstin": "nonsense"}}),
        ("bad confidence", {"f": {"gstin": {"v": None, "c": "abc"}}, "oconf": "xyz"}),
    ]:
        out = verify_extraction(raw)
        g = out["fields"]["gstin"]
        # A garbled response must never yield a valid verdict, and confidences
        # must still be ints in range so downstream scoring cannot crash.
        check(f"{label} -> not valid", g["gstin_valid"], False)
        check(f"{label} -> confidence is a clamped int",
              isinstance(g["confidence"], int) and 0 <= g["confidence"] <= 100, True)
        check(f"{label} -> envelope shape intact",
              set(out) >= {"document_type", "fields", "tamper_flag",
                           "overall_extraction_confidence"}, True)

    # A malformed ambiguity report is dropped from the output but must NOT
    # silently upgrade the read to clean — the caution signal survives.
    out = verify_extraction({"f": {"gstin": {"v": REFERENCE_GSTIN, "c": 70,
                                             "amb": [{"pos": 99, "cand": ["A"]}]}}})
    g = out["fields"]["gstin"]
    check("malformed amb -> still valid", g["gstin_valid"], True)
    check("malformed amb -> entry dropped", g["ambiguous_chars"], [])
    check("malformed amb -> flagged low confidence",
          g["gstin_valid_but_low_confidence"], True)


if __name__ == "__main__":
    print("=" * 60)
    print("GSTIN deterministic validation — verification")
    print("=" * 60)
    test_reference_vector()
    test_round_trip()
    test_mutation_sensitivity()
    test_reason_routing()
    test_ambiguity_flag()
    test_model_cannot_override()
    test_malformed_model_output()
    print("\n" + "=" * 60)
    print(f"{_passed} passed, {_failed} failed")
    print("=" * 60)
    sys.exit(1 if _failed else 0)
