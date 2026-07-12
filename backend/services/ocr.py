"""Open-source OCR (RapidOCR / ONNX) for images and scanned PDFs.

RapidOCR ships its models in the wheel and runs on CPU — no Tesseract binary and
no runtime downloads. PyMuPDF rasterizes scanned PDF pages so they can be OCR'd.

Everything here is optional and lazy: if the OCR libraries are not installed, the
functions report unavailable and the app degrades gracefully (documents are simply
treated as unverifiable, as before).
"""
from __future__ import annotations

import io
from functools import lru_cache

try:
    from rapidocr_onnxruntime import RapidOCR  # type: ignore
    _RAPID = True
except Exception:  # pragma: no cover - optional dep
    _RAPID = False

try:
    import fitz  # PyMuPDF  # type: ignore
    _FITZ = True
except Exception:  # pragma: no cover - optional dep
    _FITZ = False

try:
    import numpy as np  # type: ignore
    from PIL import Image  # type: ignore
    _IMG = True
except Exception:  # pragma: no cover - optional dep
    _IMG = False

# Cap OCR work so a huge scan can't hang a review.
_MAX_PDF_PAGES = 5
_PDF_DPI = 200


def ocr_available() -> bool:
    return _RAPID and _IMG


@lru_cache(maxsize=1)
def _engine():
    # First construction loads the ONNX models (~1-2s); cached thereafter.
    return RapidOCR()


def _run(np_img) -> tuple[str, float]:
    """Return (text, mean_confidence 0-1) for a numpy RGB image."""
    result, _ = _engine()(np_img)
    if not result:
        return "", 0.0
    texts, scores = [], []
    for item in result:
        # item = [box, text, score]
        try:
            texts.append(str(item[1]))
            scores.append(float(item[2]))
        except (IndexError, TypeError, ValueError):
            continue
    text = "\n".join(t for t in texts if t.strip())
    conf = sum(scores) / len(scores) if scores else 0.0
    return text, conf


def ocr_image(path: str) -> tuple[str, float]:
    if not ocr_available():
        return "", 0.0
    try:
        img = Image.open(path).convert("RGB")
        return _run(np.array(img))
    except Exception:
        return "", 0.0


def ocr_pdf(path: str) -> tuple[str, float]:
    """Rasterize a scanned PDF and OCR its pages."""
    if not ocr_available() or not _FITZ:
        return "", 0.0
    texts, confs = [], []
    try:
        doc = fitz.open(path)
    except Exception:
        return "", 0.0
    try:
        for i, page in enumerate(doc):
            if i >= _MAX_PDF_PAGES:
                break
            try:
                pix = page.get_pixmap(dpi=_PDF_DPI)
                img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                t, c = _run(np.array(img))
                if t.strip():
                    texts.append(t)
                    confs.append(c)
            except Exception:
                continue
    finally:
        doc.close()
    text = "\n".join(texts)
    conf = sum(confs) / len(confs) if confs else 0.0
    return text, conf
