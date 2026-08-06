"""Deterministic GSTIN validation — no LLM involved.

The extraction model transcribes a GSTIN off a document; *this* module decides
whether that string is well-formed. The split is deliberate: the mod-36 checksum
is exact arithmetic over 14 characters, and an LLM asked to do it will sometimes
report a pass on a mismatch — the worst possible failure direction for a claims
pipeline, since a format-valid-but-checksum-invalid GSTIN is the signature of a
fabricated invoice.

Checks run in order and stop at the first failure (see validate_gstin).
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

# Index 0-35. Position in this string IS the character's numeric code.
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")

# GST state/UT codes. 01-38 are the assigned range; the gaps are real (there is
# no state 00, and codes above 38 are unassigned as of the current GST list).
VALID_STATE_CODES = {f"{n:02d}" for n in range(1, 39)}

# Reasons, mirrored in the API contract. "valid" only ever comes from a full pass.
REASON_VALID = "valid"
REASON_LENGTH = "invalid_length"
REASON_FORMAT = "invalid_format"
REASON_STATE = "invalid_state_code"
REASON_PAN = "invalid_pan_segment"
REASON_CHECKSUM = "checksum_mismatch"


def compute_checksum(first_14: str) -> str:
    """Return the expected 15th character for the first 14 of a GSTIN.

    Mod-36 with alternating weights 1,2,1,2,... Each product is folded by
    (product // 36) + (product % 36) before being summed — this is the digit-sum
    step, and dropping it is the usual way this algorithm gets implemented wrong.
    """
    if len(first_14) != 14:
        raise ValueError(f"expected 14 characters, got {len(first_14)}")

    factor = 1
    total = 0
    for char in first_14:
        code = CHARSET.find(char)
        if code < 0:
            raise ValueError(f"character {char!r} is not in the GSTIN charset")
        product = factor * code
        total += (product // 36) + (product % 36)
        factor = 2 if factor == 1 else 1

    return CHARSET[(36 - (total % 36)) % 36]


def validate_gstin(
    value: Optional[str],
    ambiguous_positions: Optional[Iterable[int]] = None,
) -> dict:
    """Run checks a-f. Returns the gstin verdict block.

    `ambiguous_positions` are indices the extraction step flagged as visually
    uncertain (O/0, I/1, S/5, B/8). Any flag makes the result low-confidence even
    on a clean pass — the checksum was computed over a character we are not sure
    we read correctly, so the pass proves less than it appears to.

    The value is NOT normalized: no case folding, no whitespace stripping beyond
    the outer edges, no character substitution. "Auto-correcting" a GSTIN into
    validity is exactly the behavior that lets a fabricated one through.
    """
    ambiguous = sorted(set(ambiguous_positions or []))
    low_conf = bool(ambiguous)

    def verdict(valid: bool, reason: str) -> dict:
        return {
            "gstin_valid": valid,
            # Only meaningful on a pass; a failure is already low-confidence.
            "gstin_valid_but_low_confidence": valid and low_conf,
            "reason": reason,
            "expected_checksum_char": None,
            "ambiguous_positions": ambiguous,
        }

    if value is None:
        return {**verdict(False, REASON_LENGTH), "reason": None}

    # Only outer whitespace is forgiven — documents often pad the field.
    gstin = value.strip()

    # (a) length
    if len(gstin) != 15:
        return verdict(False, REASON_LENGTH)

    # (b) format
    if not GSTIN_RE.match(gstin):
        return verdict(False, REASON_FORMAT)

    # (c) state code
    if gstin[:2] not in VALID_STATE_CODES:
        return verdict(False, REASON_STATE)

    # (d) embedded PAN (characters 3-12, 1-indexed => [2:12])
    if not PAN_RE.match(gstin[2:12]):
        return verdict(False, REASON_PAN)

    # (e) checksum
    expected = compute_checksum(gstin[:14])
    result = verdict(expected == gstin[14],
                     REASON_VALID if expected == gstin[14] else REASON_CHECKSUM)
    result["expected_checksum_char"] = expected
    return result


def state_name(code: str) -> Optional[str]:
    """Human-readable state for a GSTIN prefix, or None if unassigned."""
    return _STATE_NAMES.get(code)


_STATE_NAMES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "28": "Andhra Pradesh (old)", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh",
}
