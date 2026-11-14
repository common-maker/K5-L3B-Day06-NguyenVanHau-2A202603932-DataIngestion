"""Fixed-size and paragraph/structure-aware chunking with metadata preservation."""
from __future__ import annotations

import re

from .ingestion import detect_section_from_text
from .models import Chunk, DocumentPage

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")


def _chunk_section(page: DocumentPage, chunk_offset: int, chunk_text: str) -> str:
    """Resolve accurate section metadata at a chunk's position within the page."""
    base_section = str(page.metadata.get("section", "body"))
    prefix_text = page.text[:chunk_offset]
    section_at_start = detect_section_from_text(prefix_text, base_section)
    # Only promote if the chunk itself opens a new section; otherwise keep start section.
    first_para = chunk_text.split("\n\n")[0]
    return detect_section_from_text(first_para, section_at_start)



def fixed_size(page: DocumentPage, size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Split normalized page text into overlapping fixed-size character windows."""
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must satisfy 0 <= overlap < size")

    text = page.text
    if not text.strip():
        return []

    chunks: list[Chunk] = []
    step = size - overlap
    start = 0
    idx = 0

    while start < len(text):
        end = min(start + size, len(text))
        window = text[start:end].strip()
        if window:
            meta = dict(page.metadata)
            meta["section"] = _chunk_section(page, start, window)
            meta["char_start"] = start
            meta["char_end"] = end
            meta["chunk_length"] = len(window)
            chunks.append(
                Chunk(
                    chunk_id=f"{page.document_id}:p{page.page:03d}:fixed:{idx:03d}",
                    document_id=page.document_id,
                    source=page.source,
                    page=page.page,
                    text=window,
                    metadata=meta,
                )
            )
            idx += 1
        if end >= len(text):
            break
        start += step

    return chunks


def _split_oversized_paragraph(para: str, max_size: int) -> list[str]:
    """Split an oversized paragraph along sentence boundaries, then words if needed."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(para) if s.strip()]
    parts: list[str] = []
    current = ""

    for sent in sentences:
        if len(sent) > max_size:
            if current:
                parts.append(current)
                current = ""
            # Word-boundary fallback for exceptionally long single sentences/lists.
            words = sent.split(" ")
            buf = ""
            for w in words:
                candidate = f"{buf} {w}".strip() if buf else w
                if len(candidate) <= max_size:
                    buf = candidate
                else:
                    if buf:
                        parts.append(buf)
                    buf = w
            if buf:
                parts.append(buf)
            continue

        candidate = f"{current} {sent}".strip() if current else sent
        if len(candidate) <= max_size:
            current = candidate
        else:
            if current:
                parts.append(current)
            current = sent

    if current:
        parts.append(current)
    return parts


def by_paragraph(page: DocumentPage, max_size: int = 1000) -> list[Chunk]:
    """Group coherent paragraphs up to `max_size` without crossing section boundaries."""
    if max_size <= 0:
        raise ValueError("max_size must be positive")
    if not page.text.strip():
        return []

    raw_paragraphs = [p.strip() for p in page.text.split("\n\n") if p.strip()]
    active_section = str(page.metadata.get("section", "body"))

    # Expand oversized paragraphs while attaching accurate section labels per unit.
    units: list[tuple[str, str]] = []
    for para in raw_paragraphs:
        active_section = detect_section_from_text(para, active_section)
        if len(para) <= max_size:
            units.append((para, active_section))
        else:
            for sub in _split_oversized_paragraph(para, max_size):
                units.append((sub, active_section))

    chunks: list[Chunk] = []
    current_texts: list[str] = []
    current_section: str | None = None
    idx = 0

    def _flush() -> None:
        nonlocal idx, current_texts, current_section
        if not current_texts:
            return
        body = "\n\n".join(current_texts).strip()
        meta = dict(page.metadata)
        meta["section"] = current_section or str(page.metadata.get("section", "body"))
        meta["chunk_length"] = len(body)
        chunks.append(
            Chunk(
                chunk_id=f"{page.document_id}:p{page.page:03d}:para:{idx:03d}",
                document_id=page.document_id,
                source=page.source,
                page=page.page,
                text=body,
                metadata=meta,
            )
        )
        idx += 1
        current_texts = []
        current_section = None

    for unit_text, unit_sec in units:
        if current_texts and unit_sec != current_section:
            _flush()

        candidate_len = (
            sum(len(t) for t in current_texts) + 2 * len(current_texts) + len(unit_text)
        )
        if current_texts and candidate_len > max_size:
            _flush()

        current_texts.append(unit_text)
        current_section = unit_sec

    _flush()
    return chunks
