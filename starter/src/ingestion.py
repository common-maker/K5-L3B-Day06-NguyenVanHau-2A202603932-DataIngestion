"""Read and normalize source data from PDF documents with full source traceability."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .models import DocumentPage

# Hyphenated left-hand tokens that legitimately retain their hyphen across line wraps.
_COMPOUND_HYPHEN_LEFT = frozenset({
    "ai",
    "context",
    "cross",
    "data",
    "decision",
    "domain",
    "end",
    "energy",
    "evidence",
    "front",
    "gai",
    "high",
    "human",
    "long",
    "low",
    "mid",
    "multi",
    "non",
    "open",
    "privacy",
    "purpose",
    "real",
    "red",
    "retrieval",
    "risk",
    "round",
    "self",
    "short",
    "socio",
    "tamper",
    "third",
    "value",
    "well",
})

_COMPOUND_HYPHEN_WORDS = frozenset({
    "pre-trained",
    "re-evaluated",
    "sub-sampling",
})

_RUNNING_HEADER_RE = re.compile(r"^NIST AI 100-1\s+AI RMF 1\.0$", re.IGNORECASE)
_RUNNING_FOOTER_RE = re.compile(r"^Page\s+(?:\d+|[ivxlcdm]+)$", re.IGNORECASE)
_STANDALONE_PAGE_NUM_RE = re.compile(r"^\d{1,3}$")
_ACTION_ID_ONLY_RE = re.compile(r"^(?:GV|MP|MS|MG)-\d+\.\d+-\d{3}$")
_STANDALONE_HEADING_RE = re.compile(
    r"^(?:Part\s+\d+:|Executive Summary$|Appendix\s+[A-D](?::|\.)|(?:\d+\.)+\s+[A-Z]|Table\s+\d+:)"
)

_BLOCK_START_RE = re.compile(
    r"^(?:"
    r"Part\s+\d+:|"
    r"Executive Summary$|"
    r"Appendix\s+[A-D](?::|\.)|"
    r"Table\s+\d+:|"
    r"Fig\.\s+\d+\.?|"
    r"\d+(?:\.\d+)*\.?\s+[A-Z]|"
    r"(?:GOVERN|MAP|MEASURE|MANAGE)\s+\d+(?:\.\d+)?\s*:|"
    r"(?:GV|MP|MS|MG)-\d+\.\d+-\d{3}\b|"
    r"Action ID\s+Suggested Action|"
    r"AI Actor Tasks:|"
    r"Trustworthy AI Characteristics:|"
    r"[•\-–]\s+"
    r")"
)


def _is_running_artifact(line: str, idx: int, total_lines: int) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if _RUNNING_HEADER_RE.match(stripped) or _RUNNING_FOOTER_RE.match(stripped):
        return True
    # Bare printed page number at very top or very bottom of extracted page text.
    if (idx <= 1 or idx >= total_lines - 2) and _STANDALONE_PAGE_NUM_RE.match(stripped):
        return True
    return False


def _join_line_pair(prev: str, curr: str) -> str:
    """Join a wrapped line onto the previous line, repairing PDF hyphenation."""
    hyphen_match = re.search(r"([A-Za-z]+)-$", prev)
    if hyphen_match:
        left = hyphen_match.group(1)
        next_word_match = re.match(r"([A-Za-z]+)", curr)
        if next_word_match:
            right = next_word_match.group(1)
            combined_hyphen = f"{left}-{right}".lower()
            if (
                left.lower() in _COMPOUND_HYPHEN_LEFT
                or combined_hyphen in _COMPOUND_HYPHEN_WORDS
                or right[0].isupper()
            ):
                return prev + curr
            return prev[:-1] + curr
    return f"{prev} {curr}"


def normalize_text(text: str) -> str:
    """Normalize Unicode (NFKC for ligatures), remove running headers/footers,
    repair PDF line-wrap hyphenation, and reconstruct logical paragraph breaks.
    """
    if not text:
        return ""

    # NFKC converts PDF typographic ligatures (fi/ff/ffi/fl) to standard ASCII letters.
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")

    raw_lines = cleaned.split("\n")
    lines = [
        re.sub(r"[ \t]+", " ", ln).strip()
        for idx, ln in enumerate(raw_lines)
        if not _is_running_artifact(ln, idx, len(raw_lines))
    ]
    if not lines:
        return ""

    paragraphs: list[str] = []
    current = lines[0]
    prev_raw_len = len(lines[0])

    for nxt in lines[1:]:
        starts_new_block = bool(_BLOCK_START_RE.match(nxt))
        # Keep bare Action IDs (e.g. GV-1.2-001) attached to their action description.
        if _ACTION_ID_ONLY_RE.match(current.strip()):
            current = f"{current} {nxt}"
            prev_raw_len = len(nxt)
            continue

        # A short raw PDF line ending with sentence punctuation (or a standalone section heading)
        # marks a visual paragraph boundary that pypdf collapsed to a single newline.
        prev_was_short_heading = (
            prev_raw_len < 55
            and len(current) < 85
            and current[-1] not in ".,;:"
            and (current == lines[0] or bool(_STANDALONE_HEADING_RE.match(current)))
            and not re.match(r"^(?:GOVERN|MAP|MEASURE|MANAGE)\s+\d+:", current)
        )
        prev_ended_paragraph = (
            len(current) >= 12
            and current[-1] in ".?!:"
            and prev_raw_len < 78
            and (nxt[0].isupper() or nxt[0] in '"“(')
        )
        if current.endswith("-") and not starts_new_block:
            current = _join_line_pair(current, nxt)
        elif starts_new_block or prev_was_short_heading or prev_ended_paragraph:
            paragraphs.append(current.strip())
            current = nxt
        else:
            current = _join_line_pair(current, nxt)
        prev_raw_len = len(nxt)

    if current.strip():
        paragraphs.append(current.strip())

    # Collapse spaces cleanly while preserving paragraph boundaries.
    normalized_paras = [re.sub(r"[ \t]+", " ", p).strip() for p in paragraphs if p.strip()]
    return "\n\n".join(normalized_paras)


def detect_section_from_text(text: str, current_section: str) -> str:
    """Update active document section from explicit verified section/function headings."""
    section = current_section
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.match(r"^Executive Summary\b", s):
            section = "executive_summary"
        elif re.match(r"^1\.\s+Introduction\b", s):
            section = "introduction"
        elif re.match(r"^Part 1:\s*Foundational", s) or re.match(r"^1\.\s+Framing Risk\b", s):
            section = "foundational"
        elif re.match(r"^2\.\s+Overview of Risks\b", s):
            section = "genai_risks"
        elif re.match(r"^(?:5\.1\s+Govern\b|GOVERN\s+\d|GV-\d)", s):
            section = "govern"
        elif re.match(r"^(?:5\.2\s+Map\b|MAP\s+\d|MP-\d)", s):
            section = "map"
        elif re.match(r"^(?:5\.3\s+Measure\b|MEASURE\s+\d|MS-\d)", s):
            section = "measure"
        elif re.match(r"^(?:5\.4\s+Manage\b|MANAGE\s+\d|MG-\d)", s):
            section = "manage"
        elif re.match(r"^6\.\s+AI RMF Profiles\b", s):
            section = "profiles"
        elif re.match(r"^Appendix\s+[A-D]\b", s):
            section = "appendix"
    return section


def _infer_page_initial_section(document_id: str, physical_page: int, prev_section: str) -> str:
    """Seed initial section state cleanly when loading partial or full page ranges."""
    if prev_section:
        return prev_section
    if document_id == "nist-ai-100-1":
        if physical_page <= 8:
            return "executive_summary"
        if physical_page <= 24:
            return "foundational"
        if physical_page <= 28:
            return "govern"
        if physical_page <= 32:
            return "map"
        if physical_page <= 35:
            return "measure"
        if physical_page <= 37:
            return "manage"
        if physical_page <= 39:
            return "profiles"
        return "appendix"
    if document_id == "nist-ai-600-1":
        if physical_page == 5:
            return "introduction"
        if physical_page <= 16:
            return "genai_risks"
        if physical_page <= 25:
            return "govern"
        if physical_page <= 31:
            return "map"
        if physical_page <= 43:
            return "measure"
        if physical_page <= 50:
            return "manage"
        return "appendix"
    return "body"


def load_pdf(
    path: Path,
    document_id: str,
    source: str,
    valid_pages: list[int] | None = None,
    base_metadata: dict[str, Any] | None = None,
    error_log: list[dict[str, Any]] | None = None,
) -> list[DocumentPage]:
    """Extract and normalize physical PDF pages, retaining source/page traceability.

    Records empty or unreadable pages in `error_log` when provided.
    """
    reader = PdfReader(str(path))
    pages_to_read = valid_pages if valid_pages is not None else list(range(1, len(reader.pages) + 1))

    result: list[DocumentPage] = []
    active_section = ""

    for page_num in pages_to_read:
        if page_num < 1 or page_num > len(reader.pages):
            if error_log is not None:
                error_log.append({
                    "document_id": document_id,
                    "source": source,
                    "page": page_num,
                    "status": "out_of_range",
                    "detail": f"Requested page {page_num} outside 1..{len(reader.pages)}",
                })
            continue

        try:
            raw_text = reader.pages[page_num - 1].extract_text() or ""
        except Exception as exc:  # pragma: no cover - defensive PDF error capture
            if error_log is not None:
                error_log.append({
                    "document_id": document_id,
                    "source": source,
                    "page": page_num,
                    "status": "extraction_error",
                    "detail": str(exc),
                })
            continue

        normalized = normalize_text(raw_text)
        if not normalized.strip():
            if error_log is not None:
                error_log.append({
                    "document_id": document_id,
                    "source": source,
                    "page": page_num,
                    "status": "empty_page",
                    "detail": "Page extracted zero characters after normalization; OCR may be needed.",
                })
            continue

        if not active_section:
            active_section = _infer_page_initial_section(document_id, page_num, active_section)
        # Determine dominant/starting section for the page and advance state across page text.
        page_section = detect_section_from_text(normalized.split("\n\n")[0], active_section)
        active_section = detect_section_from_text(normalized, active_section)

        meta = dict(base_metadata or {})
        meta["section"] = page_section
        meta["raw_chars"] = len(raw_text.strip())
        meta["normalized_chars"] = len(normalized)

        result.append(
            DocumentPage(
                document_id=document_id,
                source=source,
                page=page_num,
                text=normalized,
                metadata=meta,
            )
        )

    return result


def load_corpus_from_manifest(
    manifest_path: Path,
    project_root: Path,
) -> tuple[list[DocumentPage], list[dict[str, Any]]]:
    """Load all valid content pages declared in the corpus manifest."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    all_pages: list[DocumentPage] = []
    error_log: list[dict[str, Any]] = []

    for src in manifest["sources"]:
        pdf_path = project_root / src["source_path"]
        if not pdf_path.exists():
            raise FileNotFoundError(f"Missing corpus file: {pdf_path}")

        base_meta = {
            "year": int(src["published_year"]),
            "document_type": str(src["document_type"]),
            "version": str(src["version"]),
            "language": str(src["language"]),
            "title": str(src["title"]),
        }
        doc_pages = load_pdf(
            path=pdf_path,
            document_id=src["source_id"],
            source=src["source_path"],
            valid_pages=src["valid_content_pages"],
            base_metadata=base_meta,
            error_log=error_log,
        )
        all_pages.extend(doc_pages)

    return all_pages, error_log
