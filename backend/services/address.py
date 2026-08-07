"""Deterministic address plausibility — offline, no geocoding service.

The question this answers is not "does this building exist" (that needs a
geocoder and a contract). It is the cheaper and more useful one for fraud
screening: *is this address internally consistent?* A fabricated invoice
routinely gets the PIN code and the GSTIN state code from different places,
because the forger copies a real GSTIN off one document and invents the address
on another. Those two fields encode the state independently, so disagreement
between them is hard evidence and costs nothing to check.

Pairs with services.gstin (which validates the GSTIN itself) — this module only
ever reads the state code out of an already-validated number.
"""
from __future__ import annotations

import re
from typing import Optional

PIN_RE = re.compile(r"\b([1-9]\d{5})\b")

# Indian PIN codes encode geography in their leading digits. The first digit is
# the postal region, the first two the circle — which maps to a state or a small
# set of them. Sets, not single values, because several circles genuinely span
# more than one state/UT.
_PIN_PREFIX_STATES: dict[str, set[str]] = {
    "11": {"Delhi"},
    "12": {"Haryana"}, "13": {"Haryana", "Punjab"},
    "14": {"Punjab"}, "15": {"Punjab"}, "16": {"Punjab", "Chandigarh"},
    "17": {"Himachal Pradesh"},
    "18": {"Jammu and Kashmir"}, "19": {"Jammu and Kashmir", "Ladakh"},
    "20": {"Uttar Pradesh"}, "21": {"Uttar Pradesh"}, "22": {"Uttar Pradesh"},
    "23": {"Uttar Pradesh"},
    # 24x-26x straddles the UP/Uttarakhand split; the circle was never renumbered.
    "24": {"Uttar Pradesh", "Uttarakhand"},
    "25": {"Uttar Pradesh", "Uttarakhand"},
    "26": {"Uttar Pradesh", "Uttarakhand"},
    "27": {"Uttar Pradesh"}, "28": {"Uttar Pradesh"},
    "30": {"Rajasthan"}, "31": {"Rajasthan"}, "32": {"Rajasthan"},
    "33": {"Rajasthan"}, "34": {"Rajasthan"},
    "36": {"Gujarat"}, "37": {"Gujarat"},
    "38": {"Gujarat", "Daman and Diu", "Dadra and Nagar Haveli and Daman and Diu"},
    "39": {"Gujarat", "Daman and Diu", "Dadra and Nagar Haveli and Daman and Diu"},
    "40": {"Maharashtra"}, "41": {"Maharashtra"}, "42": {"Maharashtra"},
    "43": {"Maharashtra"}, "44": {"Maharashtra"},
    "45": {"Madhya Pradesh"}, "46": {"Madhya Pradesh"}, "47": {"Madhya Pradesh"},
    "48": {"Madhya Pradesh", "Chhattisgarh"}, "49": {"Chhattisgarh"},
    "50": {"Telangana"}, "51": {"Andhra Pradesh", "Telangana"},
    "52": {"Andhra Pradesh", "Telangana"}, "53": {"Andhra Pradesh"},
    "56": {"Karnataka"}, "57": {"Karnataka"}, "58": {"Karnataka"},
    "59": {"Karnataka"},
    # Puducherry's mainland enclaves sit inside the Tamil Nadu circle (605xxx,
    # 607xxx) and Yanam inside Andhra's (533xxx) — hence the shared prefixes.
    "60": {"Tamil Nadu", "Puducherry"}, "61": {"Tamil Nadu"},
    "62": {"Tamil Nadu"}, "63": {"Tamil Nadu"},
    "64": {"Tamil Nadu", "Puducherry"},
    "67": {"Kerala"}, "68": {"Kerala"}, "69": {"Kerala", "Lakshadweep"},
    "70": {"West Bengal"}, "71": {"West Bengal"}, "72": {"West Bengal"},
    "73": {"West Bengal"},
    "74": {"West Bengal", "Sikkim", "Andaman and Nicobar Islands"},
    "75": {"Odisha"}, "76": {"Odisha"}, "77": {"Odisha"},
    "78": {"Assam"},
    "79": {"Arunachal Pradesh", "Manipur", "Meghalaya", "Mizoram",
           "Nagaland", "Tripura"},
    "80": {"Bihar"}, "81": {"Bihar"}, "82": {"Bihar", "Jharkhand"},
    "83": {"Jharkhand"}, "84": {"Bihar"}, "85": {"Bihar"},
}

# Placeholder text that survives from an unfilled template.
# `[...]` / `<...>` are their own alternatives rather than \b-anchored ones —
# a word boundary before "[" never matches, which would silently disable them.
_PLACEHOLDER_RE = re.compile(
    r"\[[^\]]{1,40}\]|<[^>]{1,40}>|"
    r"\b(?:address\s*line\s*\d|street\s*name|city\s*name|your\s+address|"
    r"enter\s+address|123\s+main|x{3,}|n\s*/\s*a|lorem\s+ipsum)\b",
    re.I,
)

# A real postal address carries at least one of these locality words.
_LOCALITY_RE = re.compile(
    r"\b(road|rd|street|st|lane|ln|nagar|colony|layout|sector|block|phase|"
    r"cross|main|marg|puram|pura|halli|pally|palli|peta|bazar|bazaar|market|"
    r"circle|junction|opp|opposite|near|behind|floor|building|complex|"
    r"tower|plaza|avenue|extension|extn|village|taluk|tehsil|district|dist)\b",
    re.I,
)


def state_for_pin(pin: Optional[str]) -> Optional[set[str]]:
    """States a 6-digit PIN can belong to, or None if the prefix is unassigned."""
    if not pin or len(pin) != 6 or not pin.isdigit():
        return None
    return _PIN_PREFIX_STATES.get(pin[:2])


def _states_agree(a: set[str], b: str) -> bool:
    """Loose comparison — GSTIN and PIN tables spell some states differently."""
    b_low = b.lower()
    return any(s.lower() in b_low or b_low in s.lower() for s in a)


def validate_address(
    address: Optional[str],
    gstin_state: Optional[str] = None,
) -> dict:
    """Score an address string read off a document.

    `gstin_state` is the state name derived from a *validated* GSTIN's leading
    two digits (services.gstin.state_name). Pass None when the GSTIN was absent
    or failed validation — cross-checking against a state read from a number we
    already rejected proves nothing.

    Returns status ∈ {ok, suspect, missing} plus the individual findings, so a
    denial can cite which part failed rather than "address looks wrong".
    """
    issues: list[str] = []
    text = (address or "").strip()

    if not text:
        return {"status": "missing", "address": None, "pin": None,
                "pin_states": None, "gstin_state": gstin_state,
                "state_match": None, "issues": ["no address printed on the document"],
                "detail": "The document carries no address."}

    placeholders = sorted({m.group(0).strip().lower()
                           for m in _PLACEHOLDER_RE.finditer(text)})
    if placeholders:
        issues.append(f"unfilled template placeholders: {', '.join(placeholders[:3])}")

    pin_match = PIN_RE.search(text)
    pin = pin_match.group(1) if pin_match else None
    if not pin:
        issues.append("no 6-digit PIN code")

    pin_states = state_for_pin(pin)
    if pin and pin_states is None:
        issues.append(f"PIN {pin} begins with an unassigned postal prefix {pin[:2]}")

    state_match = None
    if pin_states and gstin_state:
        state_match = _states_agree(pin_states, gstin_state)
        if not state_match:
            issues.append(
                f"PIN {pin} is in {'/'.join(sorted(pin_states))} but the GSTIN "
                f"state code says {gstin_state} — the address and the tax "
                "registration disagree on the state"
            )

    if not _LOCALITY_RE.search(text):
        issues.append("no street/locality component (road, nagar, sector, …)")

    if len(text) < 15:
        issues.append(f"address is only {len(text)} characters — too short to be postal")

    # A state disagreement or template text is disqualifying on its own; the
    # softer findings only matter in combination.
    hard = state_match is False or bool(placeholders)
    status = "suspect" if hard or len(issues) >= 2 else "ok"

    return {
        "status": status,
        "address": text,
        "pin": pin,
        "pin_states": sorted(pin_states) if pin_states else None,
        "gstin_state": gstin_state,
        "state_match": state_match,
        "issues": issues,
        "detail": "; ".join(issues) if issues else "Address is internally consistent.",
    }
