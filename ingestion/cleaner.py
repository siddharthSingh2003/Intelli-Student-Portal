"""Text cleaning (M1): repeated headers/footers, page numbers, hyphenation, whitespace."""
from __future__ import annotations

import re
from collections import Counter

from ingestion.loader import PageText

PAGE_NO = re.compile(r"^\s*(page\s*)?\d+\s*(of\s*\d+)?\s*$", re.I)


def clean_pages(pages: list[PageText]) -> list[PageText]:
    repeated: set[str] = set()
    if len(pages) >= 3:   # a short line on more than half the pages is a running header/footer
        counts = Counter(l.strip() for p in pages for l in set(p.text.splitlines()) if 0 < len(l.strip()) < 100)
        repeated = {l for l, n in counts.items() if n > len(pages) / 2}
    out = []
    for p in pages:
        t = p.text.replace("\r", "")
        t = re.sub(r"[\x00-\x08\x0b\x0e-\x1f]", "", t)
        t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)                 # de-hyphenate line breaks
        lines = [l.rstrip() for l in t.splitlines()
                 if l.strip() not in repeated and not PAGE_NO.match(l)]
        t = "\n".join(lines)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t).strip()
        out.append(PageText(p.page, t, p.ocr))
    return out
