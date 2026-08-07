"""Deterministic artifact forensics — is this file a real document or a fabrication?

NO LLM. Everything here is exact, cheap, and auditable: file hashes, container
metadata, EXIF, embedded generator strings, and a small number of pixel
heuristics. The extraction agent gives a *perceptual* opinion on tampering; this
module gives *provenance* evidence, and a denial that cites "PNG carries a Stable
Diffusion prompt chunk" is defensible in a way that "the model thought it looked
off" is not.

Design rule mirrored from services.gstin: signals are reported, never
auto-corrected, and a missing capability (no PyMuPDF, no Pillow) degrades to
"unknown" rather than to "clean". An unreadable file must never score as
authentic — that is the direction fraud pushes on.
"""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Optional

try:
    # `pymupdf` is the current import name; `fitz` is the legacy alias kept for
    # older pins (and still what services.ocr uses).
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    _FITZ = True
except Exception:  # pragma: no cover - optional dep
    _FITZ = False

try:
    from PIL import Image, ExifTags
    _PIL = True
except Exception:  # pragma: no cover - optional dep
    _PIL = False


# ---- severity vocabulary -------------------------------------------------
# critical  -> on its own, enough to refuse the document
# high      -> strong fraud indicator; needs a human
# medium    -> unusual; meaningful only alongside another signal
# info      -> recorded for the audit trail, contributes no risk
_WEIGHT = {"critical": 100, "high": 45, "medium": 20, "info": 0}

# Risk at which a file stops being "authentic_likely". Set so that one high
# signal, or two independent medium ones, trips it. Two mediums is the profile
# of a generated image (no EXIF + a canvas-standard size) and of a scrubbed PDF
# (no producer + no letterhead) — neither signal is conclusive alone, which is
# why the pair is what matters. "review" only marks the document for attention;
# it never blocks on its own.
_REVIEW_RISK = 30


# ---- generator fingerprints ---------------------------------------------
# Matched case-insensitively against a PDF's Producer/Creator and an image's
# EXIF Software tag. Ordered most-specific first; the first hit wins.
_GENERATORS = (
    # Generative models. A hospital invoice has no reason to carry these.
    (r"stable\s*diffusion|comfyui|automatic1111|midjourney|dall[\-\s]?e|"
     r"firefly|imagen|flux\.1|invokeai|novelai",
     "ai_image_generator", "critical"),
    # Design / photo editors. Legitimate billing systems do not emit these.
    (r"photoshop|gimp|canva|figma|illustrator|coreldraw|affinity|inkscape|pixlr",
     "image_editor", "high"),
    # Fill-in-the-blank document builders — the usual source of template fakes.
    (r"invoice\s*generator|jotform|dochub|smallpdf|ilovepdf|pdfescape|"
     r"sejda|pdffiller|zamzar",
     "online_pdf_tool", "high"),
    # Office suites. A real hospital bill comes off a HIS/billing system, but a
    # small clinic genuinely may use Word — meaningful only in combination.
    (r"microsoft\s*word|libreoffice|openoffice|google\s*docs|pages|wps\s*office",
     "word_processor", "medium"),
    # Report/PDF libraries: ambiguous. Real billing backends use these too.
    (r"reportlab|itext|tcpdf|fpdf|wkhtmltopdf|jspdf|dompdf",
     "pdf_library", "medium"),
    # Scanners and phone scan apps — evidence FOR authenticity.
    (r"canon|epson|xerox|ricoh|kyocera|brother|hp\s*scan|scansnap|"
     r"camscanner|adobe\s*scan|genius\s*scan|office\s*lens",
     "scanner", "info"),
)

# PNG/XMP keys that carry generation provenance. Diffusion tools write the
# prompt straight into the file; most users never strip it.
_AI_METADATA_KEYS = ("parameters", "prompt", "workflow", "sd-metadata",
                     "negative_prompt", "generation_data")
_AI_XMP_MARKERS = (
    "trainedalgorithmicmedia",   # C2PA digitalSourceType for genAI
    "compositewithtrainedalgorithmicmedia",
    "c2pa.created",
    "ai_generated",
    "openai.com",
    "stability.ai",
)

# Template / specimen watermarks. Presence means the file came off a sample
# template rather than a real transaction.
_WATERMARK_TERMS = (
    "sample", "specimen", "template", "draft", "dummy", "example",
    "for demonstration", "demonstration only", "not a valid", "not valid for",
    "void", "preview only", "watermark", "lorem ipsum",
    "your company", "your logo", "company name here", "hospital name here",
    "123 main", "xxx-xxx", "test invoice", "mock",
)
_WATERMARK_RE = re.compile("|".join(re.escape(t) for t in _WATERMARK_TERMS), re.I)

# Letterhead vocabulary — a genuine hospital/pharmacy document carries at least
# some of this institutional furniture.
_LETTERHEAD_RE = re.compile(
    r"gstin|gst\s*no|regd?\.?\s*no|registration\s*no|cin\b|drug\s*licen[cs]e|"
    r"dl\s*no|tel\b|phone|ph\.?\s*no|email|www\.|@|"
    r"pin\s*code|\b\d{6}\b|receipt|invoice\s*no|bill\s*no",
    re.I,
)

# An unstamped document is only suspicious if it claims to need a stamp. Big
# hospitals issue genuine machine-generated invoices that say so in these words,
# and penalising those would flag the most legitimate documents in the set.
_COMPUTER_GENERATED_RE = re.compile(
    r"computer[\s\-]*generated|electronically\s+generated|system\s+generated|"
    r"no\s+signature\s+(?:is\s+)?required|does\s+not\s+require\s+(?:a\s+)?"
    r"(?:signature|stamp)|digitally\s+signed|e-?invoice",
    re.I,
)

# Canonical diffusion-model output sizes. Only meaningful when EXIF is absent.
_DIFFUSION_SIZES = {
    (512, 512), (768, 768), (1024, 1024), (1152, 896), (896, 1152),
    (1216, 832), (832, 1216), (1344, 768), (768, 1344), (1536, 1024),
    (1024, 1536), (2048, 2048),
}

_MAX_PDF_PAGES = 5

# --- seal / stamp detection thresholds -----------------------------------
# A rubber stamp or a pen signature is coloured ink: saturated, mid-luminance,
# and distinct from both the black text and the white paper around it. These
# bounds bracket what a stamp actually covers on a page. Below the floor is
# scanner noise and JPEG colour fringing around black text; above the ceiling
# is a colour photograph or a heavily designed letterhead, neither of which is
# a stamp.
_SEAL_MIN_SATURATION = 45   # max(R,G,B) - min(R,G,B)
_SEAL_MIN_LUMA = 30         # darker than this is black ink, not coloured
_SEAL_MAX_LUMA = 225        # lighter than this is paper
_SEAL_MIN_RATIO = 0.0015    # 0.15% of the page
_SEAL_MAX_RATIO = 0.25      # beyond this it is imagery, not a stamp
_SEAL_DPI = 130             # enough to see a stamp; cheap to rasterize


def sha256_file(path: str) -> Optional[str]:
    """Content hash — the key for exact-duplicate reuse across claims."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _detect_seal(img) -> Optional[dict]:
    """Look for a rubber stamp, seal, or pen signature by its coloured ink.

    Printed text is black or near-black: its RGB channels sit close together.
    A stamp pad and a ballpoint are blue, violet, or red — saturated ink at
    mid-luminance, which nothing else on a bill produces. Counting those pixels
    separates a document someone physically stamped and signed from one that was
    printed (or generated) and never touched.

    Returns None if the image cannot be read. `found` is None rather than False
    when the coloured area is too large to be a stamp — that is a colour photo or
    a designed letterhead, and calling it "no stamp" would be wrong.

    Deliberately a *presence* detector, not a *validity* one: it does not read
    the stamp, match it to the hospital, or claim it is genuine. A forger can
    paste a stamp image in. Absence is the informative direction.
    """
    try:
        rgb = img.convert("RGB")
        if max(rgb.size) > 1400:
            rgb.thumbnail((1400, 1400))
        w, h = rgb.size
        if w < 40 or h < 40:
            return None

        px = rgb.load()
        step = max(1, min(w, h) // 320)
        total = coloured = 0
        hues = {"blue": 0, "red": 0, "green": 0, "violet": 0}
        bottom_half = 0
        min_x = min_y = 10 ** 9
        max_x = max_y = -1

        for y in range(0, h, step):
            for x in range(0, w, step):
                r, g, b = px[x, y]
                total += 1
                hi, lo = max(r, g, b), min(r, g, b)
                if hi - lo < _SEAL_MIN_SATURATION:
                    continue
                luma = (r * 299 + g * 587 + b * 114) // 1000
                if not (_SEAL_MIN_LUMA <= luma <= _SEAL_MAX_LUMA):
                    continue
                coloured += 1
                if y > h / 2:
                    bottom_half += 1
                min_x, max_x = min(min_x, x), max(max_x, x)
                min_y, max_y = min(min_y, y), max(max_y, y)
                if b >= r and b >= g:
                    hues["violet" if r > g + 20 else "blue"] += 1
                elif r >= g:
                    hues["red"] += 1
                else:
                    hues["green"] += 1

        if not total:
            return None
        ratio = coloured / total

        # How tightly the ink clusters. A stamp occupies one region of the page;
        # colour fringing from JPEG artifacts is scattered across all of it.
        spread = None
        if coloured:
            box = ((max_x - min_x + step) * (max_y - min_y + step)) / float(w * h)
            spread = round(box, 3)

        if ratio > _SEAL_MAX_RATIO:
            found = None       # too much colour to attribute to a stamp
        elif ratio < _SEAL_MIN_RATIO:
            found = False
        else:
            found = True

        return {
            "found": found,
            "ink_ratio": round(ratio, 5),
            "dominant_hue": max(hues, key=hues.get) if coloured else None,
            "in_lower_half": round(bottom_half / coloured, 2) if coloured else None,
            "spread": spread,
        }
    except Exception:
        return None


def _match_generator(*values: Optional[str]) -> Optional[dict]:
    blob = " ".join(v for v in values if v).lower()
    if not blob.strip():
        return None
    for pattern, kind, severity in _GENERATORS:
        m = re.search(pattern, blob)
        if m:
            return {"tool": m.group(0).strip(), "kind": kind, "severity": severity}
    return None


def _signal(signals: list, code: str, severity: str, detail: str) -> None:
    signals.append({"code": code, "severity": severity, "detail": detail})


# ---- PDF ----------------------------------------------------------------
def _count_eof_markers(path: str) -> int:
    """Incremental-update count. A PDF saved once has exactly one %%EOF.

    More than one means the file was re-saved on top of itself, which is how an
    editor writes a change into an existing document without rebuilding it.
    """
    try:
        with open(path, "rb") as fh:
            return fh.read().count(b"%%EOF")
    except OSError:
        return 0


def _analyze_pdf(path: str, out: dict, signals: list) -> None:
    if not _FITZ:
        _signal(signals, "forensics_unavailable", "info",
                "PyMuPDF not installed; PDF provenance not checked")
        return
    try:
        doc = fitz.open(path)
    except Exception as exc:
        _signal(signals, "unreadable_container", "high",
                f"PDF could not be parsed: {exc}")
        return

    try:
        meta = doc.metadata or {}
        producer = (meta.get("producer") or "").strip() or None
        creator = (meta.get("creator") or "").strip() or None
        created = (meta.get("creationDate") or "").strip() or None
        modified = (meta.get("modDate") or "").strip() or None
        out.update({"producer": producer, "creator": creator,
                    "created": created, "modified": modified,
                    "page_count": doc.page_count})

        gen = _match_generator(producer, creator)
        if gen:
            out["generator"] = gen
            if gen["severity"] != "info":
                _signal(signals, f"generator_{gen['kind']}", gen["severity"],
                        f"Produced by {gen['tool']!r} ({gen['kind'].replace('_', ' ')})")
            else:
                _signal(signals, "generator_scanner", "info",
                        f"Scanner/scan-app origin: {gen['tool']!r}")
        elif not producer and not creator:
            out["metadata_stripped"] = True
            _signal(signals, "metadata_stripped", "medium",
                    "PDF carries no Producer or Creator — provenance removed")

        # Re-saved after creation. Dates are the weak form; %%EOF count is the
        # strong form because it survives metadata scrubbing.
        eofs = _count_eof_markers(path)
        out["revisions"] = max(0, eofs - 1)
        if out["revisions"] > 0:
            _signal(signals, "incremental_update", "medium",
                    f"PDF contains {out['revisions']} incremental update(s) — "
                    "content was modified after the original save")
        if created and modified and created != modified:
            _signal(signals, "modified_after_creation", "medium",
                    f"Modification date {modified} differs from creation date {created}")

        # A page that is one full-bleed image with no text layer is a photo in a
        # PDF wrapper — the standard way an edited JPEG is laundered into a
        # "scan". Distinct from a genuine scanner PDF, which says so in Producer.
        text_chars = 0
        full_page_images = 0
        pages = min(doc.page_count, _MAX_PDF_PAGES)
        for i in range(pages):
            try:
                page = doc[i]
                text_chars += len((page.get_text() or "").strip())
                page_area = abs(page.rect.width * page.rect.height) or 1
                for img in page.get_images(full=True):
                    for rect in page.get_image_rects(img[0]) or []:
                        if abs(rect.width * rect.height) / page_area > 0.85:
                            full_page_images += 1
                            break
            except Exception:
                continue
        out["text_chars"] = text_chars
        out["full_page_images"] = full_page_images
        if full_page_images and text_chars < 40:
            severity = "medium" if (out.get("generator") or {}).get("kind") == "scanner" else "high"
            _signal(signals, "image_only_pdf", severity,
                    f"{full_page_images} page(s) are a single full-page image with no "
                    "text layer — an image wrapped in a PDF, not a generated document")

        # A cryptographic signature is a stronger authenticity claim than any
        # rubber stamp, and it substitutes for one.
        try:
            out["digitally_signed"] = bool(doc.get_sigflags() > 0)
        except Exception:
            out["digitally_signed"] = False
        if out["digitally_signed"]:
            _signal(signals, "digitally_signed", "info",
                    "PDF carries a digital signature field")

        # Watermark / letterhead over the embedded text layer. OCR text is
        # folded in later by the caller for scanned pages.
        blob = "\n".join((doc[i].get_text() or "") for i in range(pages))
        _scan_text(blob, out, signals)

        # Stamp/seal: rasterize the first page and look for coloured ink.
        if _PIL:
            try:
                pix = doc[0].get_pixmap(dpi=_SEAL_DPI)
                page_img = Image.open(io.BytesIO(pix.tobytes("png")))
                out["seal"] = _detect_seal(page_img)
            except Exception:
                out["seal"] = None
        _seal_signal(out, signals)
    finally:
        doc.close()


# ---- images -------------------------------------------------------------
def _exif_dict(img) -> dict:
    try:
        raw = img.getexif()
    except Exception:
        return {}
    if not raw:
        return {}
    return {ExifTags.TAGS.get(k, str(k)): v for k, v in raw.items()}


def _analyze_image(path: str, out: dict, signals: list) -> None:
    if not _PIL:
        _signal(signals, "forensics_unavailable", "info",
                "Pillow not installed; image provenance not checked")
        return
    try:
        img = Image.open(path)
        img.load()
    except Exception as exc:
        _signal(signals, "unreadable_container", "high",
                f"Image could not be parsed: {exc}")
        return

    out["dimensions"] = list(img.size)
    info = {str(k).lower(): v for k, v in (img.info or {}).items()}

    # Diffusion tools embed the generating prompt in a PNG text chunk.
    ai_keys = [k for k in info if k in _AI_METADATA_KEYS]
    if ai_keys:
        out["ai_metadata"] = ai_keys
        _signal(signals, "ai_generation_metadata", "critical",
                f"Image embeds generation metadata ({', '.join(sorted(ai_keys))}) — "
                "this file was produced by an image-generation model")

    # C2PA / XMP provenance, including the genAI digitalSourceType.
    xmp_blob = " ".join(
        str(v) for k, v in info.items()
        if k in ("xmp", "xml:com.adobe.xmp", "comment", "description", "software")
    ).lower()
    hits = [m for m in _AI_XMP_MARKERS if m in xmp_blob]
    if hits:
        _signal(signals, "ai_provenance_marker", "critical",
                f"Embedded provenance declares AI generation ({', '.join(hits)})")

    exif = _exif_dict(img)
    make = str(exif.get("Make") or "").strip() or None
    model = str(exif.get("Model") or "").strip() or None
    software = str(exif.get("Software") or "").strip() or None
    shot_at = str(exif.get("DateTimeOriginal") or exif.get("DateTime") or "").strip() or None
    out.update({"camera": " ".join(x for x in (make, model) if x) or None,
                "software": software, "captured_at": shot_at,
                "exif_present": bool(exif)})

    gen = _match_generator(software)
    if gen:
        out["generator"] = gen
        if gen["severity"] != "info":
            _signal(signals, f"generator_{gen['kind']}", gen["severity"],
                    f"EXIF Software is {gen['tool']!r} ({gen['kind'].replace('_', ' ')})")

    if not exif:
        out["metadata_stripped"] = True
        _signal(signals, "no_exif", "medium",
                "Image has no EXIF at all — a camera photo or scan normally carries "
                "capture metadata; synthetic and screenshot images do not")
        if tuple(img.size) in _DIFFUSION_SIZES:
            _signal(signals, "diffusion_canvas_size", "medium",
                    f"{img.size[0]}x{img.size[1]} is a standard image-model output size "
                    "and the file carries no capture metadata")
    elif not (make or model) and not software:
        _signal(signals, "exif_without_camera", "medium",
                "EXIF present but no camera make/model — re-encoded by an editor")

    out["seal"] = _detect_seal(img)
    _seal_signal(out, signals)

    ela = _error_level(img)
    if ela is not None:
        out["ela_score"] = ela
        if ela >= 70:
            _signal(signals, "recompression_hotspot", "high",
                    f"Error-level analysis {ela}/100 — recompression error is "
                    "concentrated in a small region, consistent with a spliced edit")
        elif ela >= 50:
            _signal(signals, "recompression_uneven", "medium",
                    f"Error-level analysis {ela}/100 — uneven compression history")


def _error_level(img) -> Optional[int]:
    """Error Level Analysis, scored 0-100.

    Re-encode at a fixed quality and measure how concentrated the difference is.
    A single-generation photo degrades evenly, so its error is spread across the
    frame; a region pasted in from another image has a different compression
    history and lights up against a quiet background. The score is the ratio of
    the brightest tail to the mean, not the mean itself — absolute error tracks
    image content, the ratio tracks inconsistency.

    Heuristic, not proof: high-contrast line art also concentrates error. That is
    why this maps to at most a "high" signal and never to "critical".
    """
    try:
        rgb = img.convert("RGB")
        if max(rgb.size) > 1600:
            rgb.thumbnail((1600, 1600))
        buf = io.BytesIO()
        rgb.save(buf, "JPEG", quality=90)
        buf.seek(0)
        recoded = Image.open(buf).convert("RGB")

        diffs = []
        w, h = rgb.size
        step = max(1, min(w, h) // 160)  # sample a grid; full-pixel work is wasteful
        px_a, px_b = rgb.load(), recoded.load()
        for y in range(0, h, step):
            for x in range(0, w, step):
                a, b = px_a[x, y], px_b[x, y]
                diffs.append(abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2]))
        if len(diffs) < 100:
            return None

        diffs.sort()
        mean = sum(diffs) / len(diffs)
        if mean < 1.0:
            return 0  # already re-saved at this quality; ELA says nothing
        p99 = diffs[int(len(diffs) * 0.99)]
        ratio = p99 / mean
        # ratio ~4 is normal photographic falloff; >=12 is a hard hotspot.
        return max(0, min(100, int(round((ratio - 4) / 8 * 100))))
    except Exception:
        return None


def _seal_signal(out: dict, signals: list) -> None:
    """Raise the missing-stamp signal, unless the document explains its absence.

    Two things excuse an unstamped page: a digital signature (cryptographically
    stronger than ink) and an explicit "computer generated / no signature
    required" note, which large hospitals genuinely print. Without either, a bill
    that nobody stamped or signed is a page that never passed through a billing
    counter.

    Only "medium" on its own. Plenty of legitimate documents are unstamped, so
    this earns its weight in combination — an unstamped, unsigned bill with no
    letterhead and scrubbed metadata is a very different object from an unstamped
    bill off a hospital's own system.
    """
    seal = out.get("seal")
    if not seal or seal.get("found") is not False:
        return  # found one, or could not tell — either way, no finding
    if out.get("digitally_signed") or out.get("computer_generated"):
        return

    _signal(signals, "no_seal", "medium",
            "No stamp, seal, or signature ink found — the page carries no "
            "coloured ink at all, and it does not declare itself computer-"
            "generated or carry a digital signature")


# ---- shared text heuristics ---------------------------------------------
def _scan_text(text: str, out: dict, signals: list) -> None:
    """Watermark, letterhead, and computer-generated checks over readable text."""
    text = (text or "").strip()
    if not text:
        return

    # Recorded before the seal check runs so it can stand down.
    out["computer_generated"] = bool(_COMPUTER_GENERATED_RE.search(text))
    # Always set, even when empty: this dict is merged over the container-level
    # forensics for scanned files, and a missing key would silently keep a stale
    # value from the embedded-text pass.
    found = sorted({m.group(0).lower() for m in _WATERMARK_RE.finditer(text)})
    out["watermark_terms"] = found
    if found:
        _signal(signals, "template_watermark", "critical",
                f"Document carries specimen/template wording ({', '.join(found[:4])}) — "
                "this is a sample document, not a record of a real transaction")

    marks = len(set(_LETTERHEAD_RE.findall(text)))
    out["letterhead_markers"] = marks
    if len(text) > 200 and marks < 2:
        _signal(signals, "no_letterhead", "medium",
                "No institutional letterhead markers (GSTIN, registration number, "
                "phone, PIN code) — genuine hospital and pharmacy documents carry them")


def scan_extracted_text(text: str) -> dict:
    """Run the watermark/letterhead checks over OCR text from a scanned file.

    Kept separate so the caller can fold OCR output into a PDF's forensics
    without re-opening the file: _analyze_pdf only sees the embedded text layer,
    which a scanned document does not have.
    """
    out: dict = {}
    signals: list = []
    _scan_text(text, out, signals)
    return {"detail": out, "signals": signals}


# ---- entry point ---------------------------------------------------------
def analyze(path: str, filename: str) -> dict:
    """Provenance report for one stored file.

    Never raises: a file we cannot inspect returns verdict "unknown" with an
    explanatory signal, which the scoring layer must not treat as a pass.
    """
    lower = (filename or path).lower()
    signals: list = []
    out: dict = {
        "sha256": sha256_file(path),
        "size_bytes": _size(path),
        "kind": "pdf" if lower.endswith(".pdf")
                else "image" if lower.endswith((".jpg", ".jpeg", ".png"))
                else "unknown",
        "generator": None,
        "metadata_stripped": False,
        "watermark_terms": [],
        "letterhead_markers": None,
        "seal": None,
        "digitally_signed": False,
        "computer_generated": False,
    }

    if out["kind"] == "pdf":
        _analyze_pdf(path, out, signals)
    elif out["kind"] == "image":
        _analyze_image(path, out, signals)
    else:
        _signal(signals, "unsupported_type", "high",
                f"{Path(filename or path).suffix or 'file'} is not an accepted document type")

    return finalize(out, signals)


def finalize(detail: dict, signals: list) -> dict:
    """Score a signal set into the forensics envelope.

    Risk is the strongest signal plus a decayed contribution from the rest, so a
    pile of medium signals can escalate but never outranks one critical finding.
    Exposed separately from `analyze` so the caller can merge OCR-derived signals
    in before scoring.
    """
    # The seal check runs on pixels alone, which misses two things it cannot see:
    # a "computer generated" note (text, and for a scanned image only available
    # after OCR) and a stamp inked in black (indistinguishable from print by
    # colour). Both arrive later, so the finding is withdrawn here — the one
    # point where pixels, text, and the model's observation are all known.
    if (detail.get("computer_generated")
            or detail.get("digitally_signed")
            or detail.get("seal_seen_by_model")):
        signals = [s for s in signals if s["code"] != "no_seal"]

    scored = sorted((_WEIGHT.get(s["severity"], 0) for s in signals), reverse=True)
    risk = 0
    if scored:
        risk = scored[0] + sum(v // 2 for v in scored[1:])
    risk = max(0, min(100, risk))

    has_critical = any(s["severity"] == "critical" for s in signals)
    unknown = any(s["code"] in ("forensics_unavailable", "unreadable_container")
                  for s in signals)

    if has_critical:
        verdict = "synthetic_suspected"
    elif unknown:
        verdict = "unknown"
    elif risk >= _REVIEW_RISK:
        verdict = "review"
    else:
        verdict = "authentic_likely"

    return {
        **detail,
        "signals": signals,
        "risk": risk,
        "verdict": verdict,
        "authentic": verdict == "authentic_likely",
    }


def _size(path: str) -> Optional[int]:
    try:
        return Path(path).stat().st_size
    except OSError:
        return None
