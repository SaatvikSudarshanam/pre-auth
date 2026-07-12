"""File storage helpers and document text extraction (with OCR fallback).

Extraction order:
  - PDF: try embedded text via pypdf. If empty (a scanned PDF), fall back to OCR
    by rasterizing pages (PyMuPDF) and running RapidOCR.
  - Image (JPG/PNG): OCR directly with RapidOCR.

If OCR is unavailable (libraries not installed), scanned PDFs and images are
reported as unverifiable, exactly as before.
"""
import uuid
from pathlib import Path
from typing import Optional

from pypdf import PdfReader

from config import ALLOWED_MIME, UPLOAD_DIR
from services.ocr import ocr_available, ocr_image, ocr_pdf

SCANNED_NOTE = "scanned document, text unavailable"
IMAGE_NOTE = "image document, text unavailable"


def safe_ext(content_type: str, original_name: str) -> str:
    ext = ALLOWED_MIME.get((content_type or "").lower())
    if ext:
        return ext
    guessed = Path(original_name or "").suffix.lower().lstrip(".")
    return guessed if guessed in {"pdf", "jpg", "jpeg", "png"} else "bin"


def store_upload(content: bytes, content_type: str, original_name: str) -> tuple[str, str]:
    """Persist bytes; return (absolute_path, safe_filename)."""
    ext = safe_ext(content_type, original_name)
    fname = f"{uuid.uuid4().hex}.{ext}"
    dest = UPLOAD_DIR / fname
    with open(dest, "wb") as fh:
        fh.write(content)
    return str(dest), fname


def extract_pdf_text(path: str, max_chars: int = 6000) -> str:
    """Return embedded text, or the scanned sentinel if the PDF has none."""
    try:
        reader = PdfReader(path)
        chunks = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                chunks.append(txt.strip())
        joined = "\n".join(chunks).strip()
        return joined[:max_chars] if joined else SCANNED_NOTE
    except Exception:
        return SCANNED_NOTE


def extract_document(path: str, filename: str, max_chars: int = 6000) -> dict:
    """Rich extraction with OCR fallback.

    Returns: {text, source, ocr_confidence, unverifiable}
      source ∈ {pdf_text, ocr_pdf, ocr_image, none}
      ocr_confidence ∈ [0,1] when OCR was used, else None
    """
    lower = (filename or path).lower()

    if lower.endswith(".pdf"):
        embedded = extract_pdf_text(path, max_chars)
        if embedded != SCANNED_NOTE:
            return {"text": embedded, "source": "pdf_text",
                    "ocr_confidence": None, "unverifiable": False}
        # Scanned PDF → OCR the rasterized pages.
        if ocr_available():
            text, conf = ocr_pdf(path)
            if text.strip():
                return {"text": text[:max_chars], "source": "ocr_pdf",
                        "ocr_confidence": conf, "unverifiable": False}
        return {"text": SCANNED_NOTE, "source": "none",
                "ocr_confidence": None, "unverifiable": True}

    if lower.endswith((".jpg", ".jpeg", ".png")):
        if ocr_available():
            text, conf = ocr_image(path)
            if text.strip():
                return {"text": text[:max_chars], "source": "ocr_image",
                        "ocr_confidence": conf, "unverifiable": False}
        return {"text": IMAGE_NOTE, "source": "none",
                "ocr_confidence": None, "unverifiable": True}

    return {"text": "", "source": "none", "ocr_confidence": None, "unverifiable": True}


def extract_document_text(path: str, filename: str) -> Optional[str]:
    """Text for the LLM context (OCR-backed). Returns a note when unverifiable."""
    info = extract_document(path, filename)
    if info["unverifiable"]:
        lower = (filename or path).lower()
        return IMAGE_NOTE if lower.endswith((".jpg", ".jpeg", ".png")) else SCANNED_NOTE
    text = info["text"]
    if info["source"] in ("ocr_pdf", "ocr_image") and info["ocr_confidence"] is not None:
        return f"[OCR confidence {info['ocr_confidence']:.2f}]\n{text}"
    return text
