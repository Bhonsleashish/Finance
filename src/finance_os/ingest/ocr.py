"""Local OCR via Tesseract (through pytesseract). No network calls, no cloud
OCR APIs. Requires the `tesseract` binary and the German ("deu") language
pack to be installed on the machine — see README for install instructions.
"""

from __future__ import annotations

import io

from finance_os.config import load_settings
from finance_os.utils.logging import get_logger

logger = get_logger(__name__)

_tesseract_checked = False
_tesseract_available = False


def tesseract_available() -> bool:
    global _tesseract_checked, _tesseract_available
    if _tesseract_checked:
        return _tesseract_available
    _tesseract_checked = True
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        _tesseract_available = True
    except Exception as exc:  # noqa: BLE001 - any failure means "not available"
        logger.warning("Tesseract OCR not available (%s). Scanned documents will yield empty text "
                        "until `tesseract-ocr` + language packs are installed.", exc)
        _tesseract_available = False
    return _tesseract_available


def ocr_image_bytes(data: bytes) -> str:
    """Run OCR on raw image bytes and return extracted text (best-effort)."""
    if not tesseract_available():
        return ""
    import pytesseract
    from PIL import Image

    settings = load_settings()
    languages = settings.get("ocr", "languages", default="deu+eng")
    image = Image.open(io.BytesIO(data))
    try:
        return pytesseract.image_to_string(image, lang=languages)
    except pytesseract.TesseractError as exc:
        logger.warning("OCR failed (%s); retrying with default language", exc)
        return pytesseract.image_to_string(image)
