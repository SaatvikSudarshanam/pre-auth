#!/usr/bin/env python3
"""Document verification pipeline — verification script.

Run this to verify the deterministic half of document verification is working.
Usage: python verify_documents.py

Companion to verify_gstin.py, which covers the GSTIN checksum in isolation. This
covers everything built on top of it:

  1. Name matching survives OCR noise and entity suffixes without matching two
     genuinely different people or hospitals.
  2. Address plausibility catches a PIN and a GSTIN that disagree on the state.
  3. Cross-checks report `unknown` — never `pass` — when a field is missing, so a
     blank document cannot outscore a real one.
  4. File forensics identify generated, edited, watermarked, and reused files
     from real bytes on disk, not from a model's opinion.
  5. Risk scoring escalates on evidence and refuses to clear what it could not
     check.

The forensics section needs PyMuPDF and Pillow; it self-skips if they are absent
(the same degradation the runtime applies).
"""

import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent))

from services import crosscheck as cc
from services import forensics
from services.address import state_for_pin, validate_address
from services.gstin import compute_checksum
from services.matching import match_org_name, match_person_name

_passed = 0
_failed = 0
_skipped = 0


def check(label: str, got, want) -> None:
    global _passed, _failed
    if got == want:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}: expected {want!r}, got {got!r}")


def section(title: str) -> None:
    print(f"\n{title}")


VALID_GSTIN = "29AAACR5055K1Z5"
VALID_GSTIN = VALID_GSTIN[:14] + compute_checksum(VALID_GSTIN[:14])
FORGED_GSTIN = VALID_GSTIN[:14] + ("A" if VALID_GSTIN[14] != "A" else "B")

ACCOUNT = "Sri Rishitha Sajjapuram"


# ---- name matching -------------------------------------------------------
def test_person_names():
    section("Patient name vs. the signed-in account")
    m = lambda doc: match_person_name(ACCOUNT, doc)["status"]
    check("exact match", m(ACCOUNT), "match")
    check("document omits a given name", m("Rishitha Sajjapuram"), "match")
    check("initial expands", m("S. Rishitha"), "match")
    check("honorific ignored", m("Mrs. Rishitha Sajjapuram"), "match")
    check("OCR rn/m confusion tolerated", m("Rishitha Sajjapurarn"), "match")
    check("different person rejected", m("Ramesh Kumar Reddy"), "mismatch")
    check("shared surname is not identity", m("Anil Sajjapuram"), "mismatch")
    check("empty name is unknown, not a match", m(""), "unknown")
    # Short tokens get no edit budget: one character IS the difference.
    check("Ram is not Rama", match_person_name("Sita Ram", "Sita Rama")["status"],
          "mismatch")


def test_org_names():
    section("Hospital on the document vs. the hospital on the claim")
    check("registered entity name matches everyday name",
          match_org_name("Apollo Hospital", "APOLLO HOSPITALS ENTERPRISE LTD")["status"],
          "match")
    check("spacing/noise normalised",
          match_org_name("Fortis Healthcare", "Fortis Health Care")["status"], "match")
    check("unrelated hospital rejected",
          match_org_name("Apollo Hospital", "Manipal Hospital")["status"], "mismatch")
    check("sibling branches flagged, not cleared",
          match_org_name("Apollo Cradle Hospital", "Apollo Spectra Hospital")["status"],
          "partial")
    check("all-noise names fall back to full tokens",
          match_org_name("The Clinic", "The Clinic")["status"], "match")


# ---- address -------------------------------------------------------------
def test_address():
    section("Provider address plausibility")
    ok = validate_address(
        "No 154, Bannerghatta Main Road, Bengaluru, Karnataka 560076", "Karnataka")
    check("consistent address passes", ok["status"], "ok")
    check("PIN agrees with GSTIN state", ok["state_match"], True)

    clash = validate_address(
        "No 154, Bannerghatta Main Road, Bengaluru 560076", "Tamil Nadu")
    check("PIN/GSTIN state clash is suspect", clash["status"], "suspect")
    check("clash is recorded explicitly", clash["state_match"], False)

    tmpl = validate_address("[Address Line 1], 123 Main Street, XXXXX", None)
    check("unfilled template is suspect", tmpl["status"], "suspect")
    check("missing address is 'missing', not 'ok'",
          validate_address("", None)["status"], "missing")

    check("PIN prefix maps to state", sorted(state_for_pin("110001")), ["Delhi"])
    check("unassigned PIN prefix returns None", state_for_pin("990001"), None)


# ---- date parsing --------------------------------------------------------
def test_dates():
    section("Invoice date parsing")
    check("ISO", cc.parse_date("2026-03-14").isoformat(), "2026-03-14")
    check("DD/MM/YYYY", cc.parse_date("14/03/2026").isoformat(), "2026-03-14")
    check("DD-Mon-YYYY", cc.parse_date("14-Mar-2026").isoformat(), "2026-03-14")
    check("ordinal suffix", cc.parse_date("1st Jan 2026").isoformat(), "2026-01-01")
    check("unparseable returns None, never a guess",
          cc.parse_date("not a date"), None)


# ---- cross-checks --------------------------------------------------------
def _envelope(**fields):
    f = {k: {"value": v, "confidence": 90} for k, v in fields.items()}
    f.setdefault("gstin", {"value": None, "confidence": 0, "gstin_valid": False,
                           "reason": None, "state": None, "ambiguous_chars": []})
    return {"fields": f,
            "forensics": {"verdict": "authentic_likely", "signals": []}}


def _with_gstin(**overrides):
    env = _envelope()
    env["fields"]["gstin"] = {
        "value": VALID_GSTIN, "confidence": 95, "gstin_valid": True,
        "gstin_valid_but_low_confidence": False, "reason": "valid",
        "expected_checksum_char": VALID_GSTIN[14], "state": "Karnataka",
        "ambiguous_chars": [], **overrides,
    }
    return env


def test_crosschecks():
    section("Cross-checks against the account and the claim")
    check("matching patient passes",
          cc.check_patient_name(_envelope(patient_name="Rishitha Sajjapuram"),
                                ACCOUNT, "bill.pdf")["status"], "pass")
    check("different patient fails",
          cc.check_patient_name(_envelope(patient_name="Ramesh Kumar Reddy"),
                                ACCOUNT, "bill.pdf")["status"], "fail")
    check("different patient is critical",
          cc.check_patient_name(_envelope(patient_name="Ramesh Kumar Reddy"),
                                ACCOUNT, "bill.pdf")["severity"], "critical")
    check("absent patient name is unknown, not pass",
          cc.check_patient_name(_envelope(), ACCOUNT, "bill.pdf")["status"], "unknown")

    check("matching hospital passes",
          cc.check_provider(_envelope(provider_name="APOLLO HOSPITALS LTD"),
                            "Apollo Hospital", "bill.pdf")["status"], "pass")
    check("wrong hospital fails",
          cc.check_provider(_envelope(provider_name="Manipal Hospital"),
                            "Apollo Hospital", "bill.pdf")["status"], "fail")

    check("valid GSTIN passes", cc.check_gstin(_with_gstin(), "bill.pdf")["status"],
          "pass")

    forged = _with_gstin(value=FORGED_GSTIN, gstin_valid=False,
                         reason="checksum_mismatch", state=None)
    check("forged GSTIN fails", cc.check_gstin(forged, "bill.pdf")["status"], "fail")
    # A clean read of a well-formed number with a wrong check digit is
    # fabrication; the same failure on an uncertain read is not distinguishable
    # from a misread character and must not be treated as proof.
    check("confidently-read checksum mismatch is critical",
          cc.check_gstin(forged, "bill.pdf")["severity"], "critical")
    ambiguous = _with_gstin(value=FORGED_GSTIN, gstin_valid=False,
                            reason="checksum_mismatch", state=None, confidence=40,
                            ambiguous_chars=[{"position": 14, "candidates": ["A", "3"]}])
    check("ambiguously-read checksum mismatch stays high",
          cc.check_gstin(ambiguous, "bill.pdf")["severity"], "high")
    malformed = _with_gstin(value="NOTAGSTIN", gstin_valid=False,
                            reason="invalid_format", state=None)
    check("format failure is not fabrication-critical",
          cc.check_gstin(malformed, "bill.pdf")["severity"], "high")


def _sealed(found=None, hue="blue", ratio=0.02, **detail):
    env = _envelope()
    env["forensics"] = {"verdict": "authentic_likely", "signals": [],
                        "seal": None if found is None else
                                {"found": found, "ink_ratio": ratio,
                                 "dominant_hue": hue, "in_lower_half": 0.9},
                        **detail}
    return env


def test_stamp():
    section("Stamp / seal presence")
    stamped = _sealed(found=True)
    check("stamp ink detected passes",
          cc.check_stamp(stamped, "itemized_bill", "bill.pdf")["status"], "pass")

    # The colour test cannot see a black-ink stamp; the model can.
    black_stamp = _sealed(found=False)
    black_stamp["seal"] = {"present": True, "kind": "seal", "text": "PAID",
                           "computer_generated": False}
    check("model-observed stamp overrides the colour test",
          cc.check_stamp(black_stamp, "itemized_bill", "bill.pdf")["status"], "pass")

    unstamped = _sealed(found=False)
    unstamped["seal"] = {"present": False, "kind": "none", "text": None,
                         "computer_generated": False}
    got = cc.check_stamp(unstamped, "itemized_bill", "bill.pdf")
    check("unstamped bill fails", got["status"], "fail")
    check("unstamped bill is medium, not critical", got["severity"], "medium")

    check("unstamped ID proof only warns",
          cc.check_stamp(unstamped, "id_proof", "id.pdf")["status"], "warn")

    cg = _sealed(found=False, computer_generated=True)
    check("computer-generated bill is exempt",
          cc.check_stamp(cg, "itemized_bill", "bill.pdf")["status"], "pass")

    signed = _sealed(found=False, digitally_signed=True)
    check("digitally signed bill is exempt",
          cc.check_stamp(signed, "itemized_bill", "bill.pdf")["status"], "pass")

    cg_model = _sealed(found=False)
    cg_model["seal"] = {"present": False, "kind": "none", "text": None,
                        "computer_generated": True}
    check("model-reported 'computer generated' is exempt",
          cc.check_stamp(cg_model, "itemized_bill", "bill.pdf")["status"], "pass")

    check("nobody could look -> unknown, not fail",
          cc.check_stamp(_sealed(found=None), "itemized_bill", "bill.pdf")["status"],
          "unknown")


def test_amount_and_date_checks():
    section("Claim totals and dates against the documents")
    bill = _envelope(amount=5000.0)
    check("documented amount passes",
          cc.check_amounts([(bill, "itemized_bill")], 5000)["status"], "pass")
    check("over-claiming fails",
          cc.check_amounts([(bill, "itemized_bill")], 9000)["status"], "fail")
    check("under-claiming only warns",
          cc.check_amounts([(bill, "itemized_bill")], 1000)["status"], "warn")
    check("no billing document is unknown, not pass",
          cc.check_amounts([(_envelope(), "prescription")], 5000)["status"], "unknown")
    check("multiple bills are summed",
          cc.check_amounts([(_envelope(amount=3000.0), "itemized_bill"),
                            (_envelope(amount=2000.0), "itemized_bill")],
                           5000)["status"], "pass")

    today = date(2026, 3, 20)
    d = lambda iso: [(_envelope(invoice_date=iso), "bill.pdf")]
    check("same-day invoice passes",
          cc.check_dates(d("2026-03-14"), "2026-03-14", today)["status"], "pass")
    check("month-old invoice warns",
          cc.check_dates(d("2026-02-10"), "2026-03-14", today)["status"], "warn")
    check("half-year drift fails",
          cc.check_dates(d("2025-09-01"), "2026-03-14", today)["status"], "fail")
    check("future-dated invoice fails",
          cc.check_dates(d("2026-06-01"), "2026-03-14", today)["status"], "fail")


def test_reuse():
    section("Document reuse")
    check("unique documents pass",
          cc.check_reuse([("a" * 64, "x.pdf"), ("b" * 64, "y.pdf")])["status"], "pass")
    check("same file twice on one claim fails",
          cc.check_reuse([("a" * 64, "x.pdf"), ("a" * 64, "y.pdf")])["status"], "fail")
    cross = cc.check_reuse([("a" * 64, "x.pdf")], lambda digest: [42])
    check("same file on another claim fails", cross["status"], "fail")
    check("cross-claim reuse is critical", cross["severity"], "critical")


def test_risk_scoring():
    section("Risk scoring and verdicts")
    clean = [cc._check(f"c{i}", "C", "pass", "low", "") for i in range(5)]
    check("all-pass clears", cc.summarize(clean)["verdict"], "clear")
    check("all-pass scores zero risk", cc.summarize(clean)["risk"], 0)

    critical = clean + [cc._check("watermark", "W", "fail", "critical", "specimen")]
    got = cc.summarize(critical)
    check("one critical -> suspected_fraud", got["verdict"], "suspected_fraud")
    check("critical saturates risk", got["risk"], 100)
    check("critical reason is surfaced for the denial",
          got["blocking_reasons"], ["specimen"])

    check("one high failure -> review",
          cc.summarize(clean + [cc._check("gstin", "G", "fail", "high", "bad")])["verdict"],
          "review")

    # Nothing failed — but nothing could be checked either. That must not clear.
    unknowns = [cc._check(f"u{i}", "U", "unknown", "medium", "") for i in range(4)]
    check("all-unknown does not clear", cc.summarize(unknowns)["verdict"], "review")
    check("unknowns carry non-zero risk", cc.summarize(unknowns)["risk"] > 0, True)


# ---- forensics over real files -------------------------------------------
BILL = ("APOLLO HOSPITALS ENTERPRISE LTD\n"
        "154 Bannerghatta Main Road, Bengaluru, Karnataka 560076\n"
        f"GSTIN: {VALID_GSTIN}   Ph: 080-26304050   Email: billing@apollo.in\n"
        "Invoice No: INV-2026-9931      Date: 14/03/2026\n"
        f"Patient: {ACCOUNT}\n"
        "Room charges 12000\nPharmacy 3400\nTotal: 15400\n"
        "Regd. No: KA/HOSP/2004/1188\n")


def test_forensics():
    global _skipped
    section("File forensics (real files on disk)")
    try:
        import pymupdf
        from PIL import Image, PngImagePlugin
    except ImportError:
        _skipped += 1
        print("  SKIP  PyMuPDF/Pillow not installed — forensics degrade to 'unknown'")
        return

    tmp = tempfile.mkdtemp(prefix="verify_documents_")

    def make_pdf(name, text, producer=None, stamp_rgb=None,
                 stamp_box=(330, 620, 480, 720)):
        """Build a one-page PDF, optionally with a coloured rubber stamp on it."""
        path = os.path.join(tmp, name)
        doc = pymupdf.open()
        page = doc.new_page()
        y = 60
        for line in text.split("\n"):
            page.insert_text((50, y), line, fontsize=9)
            y += 14
        if stamp_rgb:
            # A double ring with a word inside — what a rubber stamp looks like.
            rect = pymupdf.Rect(*stamp_box)
            colour = tuple(c / 255 for c in stamp_rgb)
            page.draw_oval(rect, color=colour, width=3)
            page.draw_oval(rect + (8, 8, -8, -8), color=colour, width=1.5)
            page.insert_text((rect.x0 + 22, rect.y0 + 55), "PAID",
                             fontsize=16, color=colour)
        if producer:
            doc.set_metadata({**(doc.metadata or {}), "producer": producer})
        doc.save(path)
        doc.close()
        return path

    codes = lambda r: sorted(s["code"] for s in r["signals"])

    # A genuine hospital invoice is stamped at the billing counter, so the
    # baseline "clean" fixture carries one.
    genuine = forensics.analyze(
        make_pdf("genuine.pdf", BILL, "Apollo HIS Billing 4.2",
                 stamp_rgb=(20, 40, 190)), "genuine.pdf")
    check("stamped billing-system PDF is clean", genuine["verdict"],
          "authentic_likely")
    check("clean PDF raises no signals", codes(genuine), [])
    check("content hash computed", len(genuine["sha256"]), 64)

    spec = forensics.analyze(
        make_pdf("specimen.pdf", "SPECIMEN - NOT A VALID DOCUMENT\n" + BILL,
                 "Apollo HIS Billing 4.2"), "specimen.pdf")
    check("specimen watermark -> synthetic_suspected", spec["verdict"],
          "synthetic_suspected")
    check("watermark term captured", "specimen" in spec["watermark_terms"], True)

    psd = forensics.analyze(
        make_pdf("psd.pdf", BILL, "Adobe Photoshop 26.0"), "psd.pdf")
    check("image-editor origin flagged",
          "generator_image_editor" in codes(psd), True)

    gen = forensics.analyze(
        make_pdf("gen.pdf", BILL, "Free Invoice Generator v3"), "gen.pdf")
    check("online invoice builder flagged",
          "generator_online_pdf_tool" in codes(gen), True)

    bare = forensics.analyze(
        make_pdf("bare.pdf", "Bill for treatment. Amount 15400.\n"
                             + "detail line for the bill\n" * 12), "bare.pdf")
    check("scrubbed metadata flagged", "metadata_stripped" in codes(bare), True)
    check("absent letterhead flagged", "no_letterhead" in codes(bare), True)
    check("two independent mediums -> review", bare["verdict"], "review")

    edited_path = make_pdf("edited.pdf", BILL, "Apollo HIS Billing 4.2")
    doc = pymupdf.open(edited_path)
    doc[0].insert_text((50, 400), "REVISED TOTAL: 45000", fontsize=9)
    doc.save(edited_path, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
    doc.close()
    edited = forensics.analyze(edited_path, "edited.pdf")
    check("re-saved PDF flagged", "incremental_update" in codes(edited), True)

    img_path = os.path.join(tmp, "page.png")
    Image.new("RGB", (900, 1200), (240, 240, 235)).save(img_path)
    wrapped_path = os.path.join(tmp, "wrapped.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(0, 0, 595, 842), filename=img_path)
    doc.save(wrapped_path)
    doc.close()
    check("image wrapped in a PDF flagged",
          "image_only_pdf" in codes(forensics.analyze(wrapped_path, "wrapped.pdf")),
          True)

    ai_path = os.path.join(tmp, "ai.png")
    meta = PngImagePlugin.PngInfo()
    meta.add_text("parameters", "hospital invoice, photorealistic, Steps: 30")
    Image.new("RGB", (1024, 1024), (250, 250, 250)).save(ai_path, pnginfo=meta)
    ai = forensics.analyze(ai_path, "ai.png")
    check("diffusion prompt chunk -> synthetic_suspected", ai["verdict"],
          "synthetic_suspected")
    check("generation metadata key captured", ai["ai_metadata"], ["parameters"])

    plain_path = os.path.join(tmp, "plain1024.png")
    Image.new("RGB", (1024, 1024), (255, 255, 255)).save(plain_path)
    plain = forensics.analyze(plain_path, "plain1024.png")
    check("missing EXIF flagged", "no_exif" in codes(plain), True)
    check("model canvas size flagged", "diffusion_canvas_size" in codes(plain), True)
    check("stripped image -> review", plain["verdict"], "review")

    photo_path = os.path.join(tmp, "photo.jpg")
    img = Image.new("RGB", (3024, 4032), (200, 195, 190))
    exif = img.getexif()
    exif[271], exif[272] = "Apple", "iPhone 15 Pro"
    exif[306] = "2026:03:14 10:22:31"
    img.save(photo_path, "JPEG", quality=92, exif=exif)
    photo = forensics.analyze(photo_path, "photo.jpg")
    check("camera EXIF read", photo["camera"], "Apple iPhone 15 Pro")
    check("genuine photo is clean", photo["verdict"], "authentic_likely")

    # A scan of a stamped paper bill — the same detector, a different container.
    scan_path = os.path.join(tmp, "scan.jpg")
    img = Image.new("RGB", (1700, 2200), (248, 247, 244))
    for yy in range(1700, 1850):
        for xx in range(900, 1150):
            img.putpixel((xx, yy), (30, 50, 180))
    exif = img.getexif()
    exif[305], exif[271] = "CamScanner", "CamScanner"
    img.save(scan_path, "JPEG", quality=90, exif=exif)
    scanned = forensics.analyze(scan_path, "scan.jpg")
    check("stamp on a scanned image is detected", scanned["seal"]["found"], True)
    check("scan-app origin is not penalised", scanned["risk"], 0)

    broken_path = os.path.join(tmp, "broken.pdf")
    Path(broken_path).write_bytes(b"%PDF-1.4 truncated garbage")
    broken = forensics.analyze(broken_path, "broken.pdf")
    check("unparseable file -> unknown", broken["verdict"], "unknown")
    check("unparseable file is never 'authentic'", broken["authentic"], False)

    # --- stamp detection over real pixels ---------------------------------
    check("blue stamp ink is detected", genuine["seal"]["found"], True)
    check("stamp hue identified", genuine["seal"]["dominant_hue"], "blue")

    unstamped = forensics.analyze(
        make_pdf("unstamped.pdf", BILL, "Apollo HIS Billing 4.2"), "unstamped.pdf")
    check("plain printed page has no stamp ink", unstamped["seal"]["found"], False)
    check("unstamped page is flagged", "no_seal" in codes(unstamped), True)

    cg = forensics.analyze(
        make_pdf("cg.pdf", BILL + "This is a computer generated invoice.\n",
                 "Apollo HIS Billing 4.2"), "cg.pdf")
    check("computer-generated note recorded", cg["computer_generated"], True)
    check("computer-generated page is exempt from the stamp check",
          "no_seal" in codes(cg), False)

    red = forensics.analyze(
        make_pdf("red.pdf", BILL, "Apollo HIS Billing 4.2",
                 stamp_rgb=(200, 20, 20)), "red.pdf")
    check("red stamp ink is detected", red["seal"]["found"], True)
    check("red hue identified", red["seal"]["dominant_hue"], "red")

    copy_path = os.path.join(tmp, "copy.pdf")
    shutil.copy(genuine_src := make_pdf("orig.pdf", BILL, "Apollo HIS Billing 4.2"),
                copy_path)
    check("identical bytes share a hash",
          forensics.sha256_file(genuine_src) == forensics.sha256_file(copy_path), True)

    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    print("=" * 66)
    print("Document verification pipeline — deterministic checks")
    print("=" * 66)
    test_person_names()
    test_org_names()
    test_address()
    test_dates()
    test_crosschecks()
    test_stamp()
    test_amount_and_date_checks()
    test_reuse()
    test_risk_scoring()
    test_forensics()
    print("\n" + "=" * 66)
    print(f"{_passed} passed, {_failed} failed"
          + (f", {_skipped} section(s) skipped" if _skipped else ""))
    print("=" * 66)
    sys.exit(1 if _failed else 0)
