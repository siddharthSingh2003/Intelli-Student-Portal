"""Chunking (M1). Two strategies, compared in the evaluation:

* section (default): split at clause/section headings ("7.2 Minimum attendance ...")
  and never let a chunk cross a section boundary, so every chunk carries the exact
  section number used in citations (R2) and by rule extraction.
* fixed: plain sliding character windows across the whole document; the section
  recorded is the one in force where the window starts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ingestion.loader import PageText

HEADING_RE = re.compile(
    r"^\s*(?:(?:Clause|Section|Rule|Regulation|Article)\s+)?(\d{1,2}(?:\.\d{1,2}){0,3})[.)]?\s+(?=[A-Z(])")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    section: str
    heading: str
    page: int
    page_end: int


@dataclass
class _Unit:
    section: str
    heading: str
    page: int
    text: str


def _units(pages: list[PageText]) -> list[_Unit]:
    units: list[_Unit] = []
    section, heading = "0", ""
    for p in pages:
        buf: list[str] = []
        for line in p.text.splitlines():
            m = HEADING_RE.match(line)
            if m and len(line.strip()) < 400:
                if buf:
                    units.append(_Unit(section, heading, p.page, "\n".join(buf)))
                    buf = []
                section, heading = m.group(1), line.strip()[:120]
            buf.append(line)
        if buf:
            units.append(_Unit(section, heading, p.page, "\n".join(buf)))
    return [u for u in units if u.text.strip()]


def _window(units: list[_Unit], size: int, overlap: int, respect_sections: bool):
    groups: list[list[_Unit]] = []
    for u in units:
        if respect_sections and groups and groups[-1][-1].section == u.section:
            groups[-1].append(u)
        elif respect_sections or not groups:
            groups.append([u])
        else:
            groups[-1].append(u)
    for g in groups:
        text, offsets = "", []
        for u in g:
            offsets.append((len(text), u))
            text += u.text.strip() + "\n"
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                cut = max(text.rfind("\n", start + size // 2, end), text.rfind(". ", start + size // 2, end))
                if cut > start:
                    end = cut + 1
            piece = text[start:end].strip()
            first = [u for off, u in offsets if off <= start][-1]
            last = [u for off, u in offsets if off < end][-1]
            if piece:
                yield first, last, piece
            if end >= len(text):
                break
            nxt = max(end - overlap, start + 1)
            sp = text.find(" ", nxt)
            start = sp + 1 if 0 <= sp < end else nxt


def chunk_pages(pages: list[PageText], doc_id: str, strategy: str = "section",
                size: int = 900, overlap: int = 150) -> list[Chunk]:
    chunks = []
    for i, (first, last, piece) in enumerate(_window(_units(pages), size, overlap, strategy == "section")):
        prefix = f"[{doc_id} | Section {first.section}] " if first.section != "0" else f"[{doc_id}] "
        chunks.append(Chunk(chunk_id=f"{doc_id}::{i:04d}", doc_id=doc_id, text=prefix + piece,
                            section=first.section, heading=first.heading, page=first.page, page_end=last.page))
    return chunks
