"""Document loader + text extraction (M1).

PDF: PyMuPDF text per page; pages with almost no text layer are scanned -> OCR
(pytesseract at 300 dpi). Tables are extracted with pdfplumber and appended as
pipe-delimited rows so fee/grade/credit tables stay retrievable row by row.
Also accepts .txt/.md (form-feed = page break) and images (OCR).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)
OCR_MIN_CHARS = 40


@dataclass
class PageText:
    page: int
    text: str
    ocr: bool = False


def load_document(path: str | Path) -> list[PageText]:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".txt", ".md"):
        raw = p.read_text(encoding="utf-8", errors="replace")
        return [PageText(i + 1, t) for i, t in enumerate(raw.split("\f"))]
    if ext == ".pdf":
        return _load_pdf(p)
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        from PIL import Image
        return [PageText(1, _ocr_image(Image.open(p)), ocr=True)]
    raise ValueError(f"Unsupported file type: {ext} (use PDF, TXT, MD or an image)")


def _load_pdf(path: Path) -> list[PageText]:
    import fitz  # PyMuPDF

    tables = _extract_tables(path)
    pages = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text, ocr = page.get_text("text"), False
            if len(text.strip()) < OCR_MIN_CHARS:          # scanned page
                ocr_text = _ocr_page(page)
                if ocr_text.strip():
                    text, ocr = ocr_text, True
            if tables.get(i):
                text += "\n\n" + "\n\n".join(tables[i])
            pages.append(PageText(i, text, ocr))
    return pages


def _ocr_page(page) -> str:
    try:
        from PIL import Image
        pix = page.get_pixmap(dpi=300)
        return _ocr_image(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    except Exception as e:  # noqa: BLE001
        log.warning("OCR unavailable or failed on page %s: %s", page.number + 1, e)
        return ""


def _ocr_image(img) -> str:
    import pytesseract
    cmd = _tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        return pytesseract.image_to_string(img)
    except pytesseract.TesseractNotFoundError as e:
        # a ValueError reaches the uploader as a clear 422 instead of a server error
        raise ValueError("OCR is needed for this file but Tesseract is not installed "
                         "(set TESSERACT_CMD to tesseract.exe if it is not on PATH)") from e


def _tesseract_cmd() -> str:
    """TESSERACT_CMD if set; else the default Windows install location when it is not on PATH."""
    import os
    import shutil
    env = os.getenv("TESSERACT_CMD", "").strip()
    if env:
        return env
    default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    return str(default) if not shutil.which("tesseract") and default.exists() else ""


def _extract_tables(path: Path) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                for t in page.extract_tables() or []:
                    rows = [" | ".join((c or "").replace("\n", " ").strip() for c in row) for row in t if row]
                    rows = [r for r in rows if r.strip(" |")]
                    if len(rows) >= 2:
                        out.setdefault(i, []).append(f"[Table, page {i}]\n" + "\n".join(rows))
    except Exception as e:  # noqa: BLE001
        log.info("table extraction skipped for %s: %s", path.name, e)
    return out
