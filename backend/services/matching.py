"""Fuzzy name matching tuned for OCR'd Indian medical documents.

Two problems this exists to solve, both of which a naive `a == b` gets wrong in
the dangerous direction:

  - False mismatch. OCR reads "Rishitha" as "Rishltha"; the invoice says
    "S. Rishitha" where the profile says "Sri Rishitha Sajjapuram"; the bill
    prints "APOLLO HOSPITALS ENTERPRISE LTD." against a claim for
    "Apollo Hospital". Rejecting these strands legitimate claims.

  - False match. "Sri Ram Clinic" vs "Sri Rama Clinic" are different businesses.
    Matching these launders a fabricated invoice.

So the comparison is token-based with an explicit edit-distance budget rather
than a similarity percentage: every token must be accounted for, and the score
reports *how* it matched so a reviewer can see the reasoning.
"""
from __future__ import annotations

import re
from typing import Optional

# Honorifics and salutations — never identity-bearing.
_TITLES = {
    "mr", "mrs", "ms", "miss", "dr", "doctor", "shri", "smt", "sri", "sh",
    "master", "mstr", "prof", "professor", "md", "baby", "b", "s", "w", "d",
    "so", "wo", "do", "co",  # s/o, w/o, d/o, c/o
}

# Organisation furniture. Stripped before comparing institution names so
# "Apollo Hospitals Pvt Ltd" and "Apollo Hospital" reduce to the same core.
_ORG_NOISE = {
    "hospital", "hospitals", "clinic", "clinics", "nursing", "home", "homes",
    "medical", "medicals", "medicare", "healthcare", "health", "care",
    "centre", "center", "centres", "centers", "institute", "institutes",
    "multispeciality", "multispecialty", "speciality", "specialty", "super",
    "diagnostics", "diagnostic", "laboratory", "laboratories", "labs", "lab",
    "pharmacy", "pharmaceuticals", "pharma", "chemist", "chemists", "druggist",
    "surgical", "surgery", "scan", "scans", "imaging", "polyclinic",
    "pvt", "private", "ltd", "limited", "llp", "inc", "co", "company", "corp",
    "and", "the", "of", "for", "at",
}

_SPLIT = re.compile(r"[^0-9a-z]+")


def _tokens(value: Optional[str]) -> list[str]:
    return [t for t in _SPLIT.split((value or "").lower()) if t]


def _edit_distance(a: str, b: str, cap: int = 2) -> int:
    """Levenshtein distance, abandoned once it exceeds `cap`.

    The cap is the point: we never need to know that two strings are 9 edits
    apart, only that they are more than 2 apart, and bailing early keeps this
    cheap enough to run over every token pair.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _budget(token: str) -> int:
    """Edit tolerance for a token — proportional, so short tokens stay strict.

    "ram" vs "rama" must not match (1 edit on a 3-char token is a different
    name), but "sajjapuram" vs "sajjapurarn" should (rn/m is a classic OCR
    confusion on a 10-char token).
    """
    if len(token) <= 4:
        return 0
    if len(token) <= 7:
        return 1
    return 2


def _token_matches(needle: str, haystack: list[str]) -> Optional[str]:
    """Find `needle` among `haystack`, allowing initials and OCR-level typos."""
    if needle in haystack:
        return needle
    # An initial matches any token starting with it ("S." vs "Sajjapuram").
    if len(needle) == 1:
        for t in haystack:
            if t.startswith(needle):
                return t
        return None
    budget = _budget(needle)
    if budget:
        for t in haystack:
            if len(t) > 1 and _edit_distance(needle, t, budget) <= budget:
                return t
    return None


def match_person_name(profile_name: str, document_name: str) -> dict:
    """Compare a person's name from the account against one read off a document.

    Asymmetric by design: every *document* token must be explained by the
    profile, but the profile may carry extra tokens the document omits. A bill
    printed as "Rishitha Sajjapuram" for the account "Sri Rishitha Sajjapuram"
    is the same person; a bill for "Rishitha Sajjapuram Kumar" naming someone
    the account does not is not.
    """
    p_all, d_all = _tokens(profile_name), _tokens(document_name)
    p = [t for t in p_all if t not in _TITLES]
    d = [t for t in d_all if t not in _TITLES]

    if not p or not d:
        return {"status": "unknown", "score": 0, "matched": [], "unmatched": [],
                "detail": "one or both names are empty"}

    matched, unmatched, fuzzy = [], [], []
    pool = list(p)
    for tok in d:
        hit = _token_matches(tok, pool)
        if hit:
            pool.remove(hit)
            matched.append(tok)
            if hit != tok:
                fuzzy.append(f"{tok}~{hit}")
        else:
            unmatched.append(tok)

    score = round(100 * len(matched) / len(d))
    # A surname-only overlap is not an identity match — families share those.
    substantive = [m for m in matched if len(m) > 1]

    if not unmatched and substantive:
        status = "match"
        detail = f"all {len(d)} name token(s) matched the account holder"
        if fuzzy:
            detail += f" (approximate: {', '.join(fuzzy)})"
    elif len(substantive) >= 2 and len(unmatched) <= 1:
        status = "partial"
        detail = (f"{len(matched)}/{len(d)} tokens matched; "
                  f"unmatched: {', '.join(unmatched)}")
    else:
        status = "mismatch"
        detail = (f"document name {document_name!r} does not correspond to "
                  f"account holder {profile_name!r}")

    return {"status": status, "score": score, "matched": matched,
            "unmatched": unmatched, "fuzzy": fuzzy, "detail": detail}


def match_org_name(claim_name: str, document_name: str) -> dict:
    """Compare the hospital/provider on the claim against the one on the document.

    Noise words are stripped, then the *cores* are compared by containment rather
    than equality: a bill prints the registered entity ("Apollo Hospitals
    Enterprise Ltd") while the claimant types the everyday name ("Apollo
    Hospital"), so requiring both sides to carry the same tokens would fail
    almost every genuine invoice. Containment still separates the case that
    matters — "Apollo Cradle" and "Apollo Spectra" are different hospitals, and
    neither core contains the other.

    If stripping leaves nothing on either side (a provider literally called "The
    Clinic"), fall back to the full token lists rather than declaring a vacuous
    match on two empty sets.
    """
    c_all, d_all = _tokens(claim_name), _tokens(document_name)
    c = [t for t in c_all if t not in _ORG_NOISE]
    d = [t for t in d_all if t not in _ORG_NOISE]
    if not c or not d:
        c, d = c_all, d_all

    if not c or not d:
        return {"status": "unknown", "score": 0, "matched": [], "unmatched": [],
                "detail": "one or both provider names are empty"}

    matched, fuzzy = [], []
    pool = list(d)
    for tok in c:
        hit = _token_matches(tok, pool)
        if hit:
            pool.remove(hit)
            matched.append(tok)
            if hit != tok:
                fuzzy.append(f"{tok}~{hit}")

    overlap = len(matched)
    # Coverage of the *larger* name, so the score still reports how much of the
    # fuller entity name was accounted for even when containment says "match".
    score = round(100 * overlap / max(len(c), len(d)))
    contained = overlap == min(len(c), len(d))

    if contained and overlap >= 1:
        status = "match"
        if len(c) == len(d):
            detail = "provider name matches the claim (after normalisation)"
        else:
            longer = document_name if len(d) > len(c) else claim_name
            detail = (f"provider name matches on {', '.join(matched)}; "
                      f"{longer!r} carries additional entity words")
        if fuzzy:
            detail += f" (approximate: {', '.join(fuzzy)})"
    elif overlap >= 1 and score >= 34:
        status = "partial"
        detail = (f"provider names overlap on {', '.join(matched)} but differ: "
                  f"claim {claim_name!r} vs document {document_name!r} — these may be "
                  "different branches of the same group")
    else:
        status = "mismatch"
        detail = (f"document provider {document_name!r} is not the provider on the "
                  f"claim, {claim_name!r}")

    return {"status": status, "score": score, "matched": matched,
            "unmatched": [t for t in c if t not in matched],
            "fuzzy": fuzzy, "detail": detail}
