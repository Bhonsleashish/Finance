"""Extract text from PDFs using PyMuPDF, falling back to OCR (Tesseract) for
scanned pages / image-only PDFs. Runs entirely offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from finance_os.config import load_settings
from finance_os.ingest.ocr import ocr_image_bytes
from finance_os.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    method: str  # 'native_text' | 'ocr'


@dataclass
class ExtractedDocument:
    pages: list[ExtractedPage]
    method: str  # overall: 'native_text' | 'ocr' | 'mixed'

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)


def extract_pdf(path: Path) -> ExtractedDocument:
    settings = load_settings()
    min_chars = settings.get("ocr", "min_native_chars", default=40)
    dpi = settings.get("ocr", "render_dpi", default=300)

    doc = fitz.open(str(path))
    pages: list[ExtractedPage] = []
    try:
        for i, page in enumerate(doc):
            native_text = page.get_text("text") or ""
            if len(native_text.strip()) >= min_chars:
                pages.append(ExtractedPage(page_number=i, text=native_text, method="native_text"))
                continue
            # Fall back to OCR: render page to an image and run tesseract.
            logger.info("Page %d of %s has little/no text layer, falling back to OCR", i, path.name)
            zoom = dpi / 72
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img_bytes = pix.tobytes("png")
            ocr_text = ocr_image_bytes(img_bytes)
            pages.append(ExtractedPage(page_number=i, text=ocr_text, method="ocr"))
    finally:
        doc.close()

    methods = {p.method for p in pages}
    overall = methods.pop() if len(methods) == 1 else "mixed"
    return ExtractedDocument(pages=pages, method=overall)


def extract_image(path: Path) -> ExtractedDocument:
    """Extract text from a standalone image (screenshot/photo receipt) via OCR."""
    with path.open("rb") as fh:
        data = fh.read()
    text = ocr_image_bytes(data)
    return ExtractedDocument(pages=[ExtractedPage(page_number=0, text=text, method="ocr")], method="ocr")
