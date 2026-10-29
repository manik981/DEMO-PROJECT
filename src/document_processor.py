"""File validation, text extraction and page-aware chunking.

Uploaded files are untrusted data. This module never executes or instructs on
document content; it only extracts text and records page metadata.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import docx
import fitz  # PyMuPDF

from .config import SUPPORTED_EXTENSIONS


class DocumentError(ValueError):
    """A user-actionable document problem (never includes document contents)."""


@dataclass
class PageText:
    """Text for one PDF page. DOCX/TXT have no reliable pages, so page_number is None."""

    page_number: int | None
    text: str


@dataclass
class ExtractedDocument:
    filename: str
    file_type: str
    pages: list[PageText]
    warnings: list[str] = field(default_factory=list)
    char_count: int = 0
    truncated: bool = False

    @property
    def full_text(self) -> str:
        parts = []
        for page in self.pages:
            if page.page_number is not None:
                parts.append(f"[Page {page.page_number}]\n{page.text}")
            else:
                parts.append(page.text)
        return "\n\n".join(parts).strip()

    @property
    def page_count(self) -> int:
        return sum(1 for page in self.pages if page.page_number is not None)

    def page_text(self, page_number: int | None) -> str:
        if page_number is None:
            return self.full_text
        return "\n".join(p.text for p in self.pages if p.page_number == page_number)

    def page_map(self) -> dict[int, str]:
        return {p.page_number: p.text for p in self.pages if p.page_number is not None}


@dataclass
class TextChunk:
    index: int
    text: str
    page_start: int | None
    page_end: int | None

    @property
    def label(self) -> str:
        if self.page_start and self.page_end and self.page_start != self.page_end:
            return f"pages {self.page_start}-{self.page_end}"
        if self.page_start:
            return f"page {self.page_start}"
        return "document body"


INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above)\s+instructions"
    r"|disregard\s+.{0,30}instructions"
    r"|reveal\s+.{0,20}(api[ _-]?key|secret|system\s+prompt)"
    r"|you\s+are\s+now\s+"
    r"|new\s+system\s+instructions"
    r"|override\s+.{0,25}(rules|instructions))",
    re.IGNORECASE,
)


def _extension(filename: str) -> str:
    if not filename:
        raise DocumentError("No file was provided.")
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise DocumentError(f"Unsupported file type '{extension or 'none'}'. Supported formats: {supported}.")
    return extension


def validate_upload(filename: str, size_bytes: int, max_bytes: int) -> str:
    """Validate name, extension and size. Returns the lowercase extension."""
    extension = _extension(filename)
    if size_bytes <= 0:
        raise DocumentError("The uploaded file is empty (0 bytes).")
    if size_bytes > max_bytes:
        raise DocumentError(
            f"The file is {size_bytes / (1024 * 1024):.1f} MB, which exceeds the "
            f"{max_bytes / (1024 * 1024):.0f} MB upload limit. Upload a smaller document."
        )
    return extension


def extract_document(data: bytes, filename: str, max_chars: int) -> ExtractedDocument:
    """Extract text from PDF, DOCX or TXT bytes without writing anything to disk."""
    extension = _extension(filename)
    if not data:
        raise DocumentError("The uploaded file is empty (0 bytes).")
    if extension == ".pdf":
        pages = _extract_pdf(data)
    elif extension == ".docx":
        pages = _extract_docx(data, filename)
    else:
        pages = _extract_txt(data)

    if not any(page.text.strip() for page in pages):
        raise DocumentError(
            "No extractable text was found. If this is a scanned PDF, OCR is not supported "
            "in this MVP - upload a text-based PDF, DOCX or TXT file."
        )

    warnings: list[str] = []
    if extension == ".pdf":
        empty_pages = [p.page_number for p in pages if p.page_number is not None and not p.text.strip()]
        if empty_pages:
            preview = ", ".join(str(n) for n in empty_pages[:10])
            suffix = "..." if len(empty_pages) > 10 else ""
            warnings.append(
                f"{len(empty_pages)} page(s) contained no extractable text (pages {preview}{suffix}). "
                "They may be scanned images; OCR is not supported."
            )
    else:
        warnings.append(
            "Page numbers are only available for PDF files. Citations for this "
            f"{extension.lstrip('.').upper()} file are limited to document-level evidence."
        )

    if INJECTION_PATTERNS.search("\n".join(page.text for page in pages)):
        warnings.append(
            "The document contains text resembling prompt-injection instructions. "
            "It is treated as untrusted content and is never executed."
        )

    extracted = _truncate_pages(pages, max_chars)
    if extracted != pages:
        warnings.append(
            f"The document was truncated to the first {max_chars:,} characters to keep API "
            "requests bounded. Upload a smaller document for complete coverage."
        )
    truncated = extracted != pages
    pages = extracted
    char_count = sum(len(page.text) for page in pages)
    return ExtractedDocument(
        filename=Path(filename).name,
        file_type=extension.lstrip("."),
        pages=pages,
        warnings=warnings,
        char_count=char_count,
        truncated=truncated,
    )


def _extract_pdf(data: bytes) -> list[PageText]:
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several low-level exception types
        raise DocumentError("The PDF could not be opened. It may be corrupted or password-protected.") from exc
    try:
        if document.needs_pass:
            raise DocumentError("The PDF is password-protected. Upload an unprotected copy.")
        if document.page_count == 0:
            raise DocumentError("The PDF contains no pages.")
        return [PageText(page_number=i + 1, text=page.get_text("text") or "") for i, page in enumerate(document)]
    finally:
        document.close()


def _extract_docx(data: bytes, filename: str) -> list[PageText]:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentError("The DOCX file could not be opened. It may be corrupted.") from exc

    # Preserve paragraph/table order; python-docx exposes no page numbers.
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, document).text.strip()
            if text:
                blocks.append(text)
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    blocks.append(" | ".join(cells))
    text = "\n".join(blocks)
    return [PageText(page_number=None, text=text)] if text.strip() else []


def _extract_txt(data: bytes) -> list[PageText]:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 always succeeds, kept as an explicit guard
        raise DocumentError("The text file encoding could not be detected. Save it as UTF-8.")
    return [PageText(page_number=None, text=text)] if text.strip() else []


def _truncate_pages(pages: list[PageText], max_chars: int) -> list[PageText]:
    """Trim to max_chars while keeping page structure intact."""
    if sum(len(p.text) for p in pages) <= max_chars:
        return pages
    result: list[PageText] = []
    remaining = max_chars
    for page in pages:
        if remaining <= 0:
            break
        text = page.text[:remaining]
        if text:
            result.append(PageText(page_number=page.page_number, text=text))
        remaining -= len(text)
    return result


def build_chunks(
    document: ExtractedDocument,
    chunk_chars: int,
    overlap_chars: int,
    max_chunks: int,
) -> tuple[list[TextChunk], list[str]]:
    """Page-aware chunking with bounded page counts and overlap inside long pages."""
    pages = [page for page in document.pages if page.text.strip()]
    if not pages:
        raise DocumentError("No extractable text was found in the document.")

    overlap_chars = max(0, min(overlap_chars, chunk_chars // 2))
    chunks: list[TextChunk] = []
    buffer_parts: list[str] = []
    buffer_pages: list[int] = []
    buffer_len = 0

    def flush() -> None:
        nonlocal buffer_parts, buffer_pages, buffer_len
        if not buffer_parts:
            return
        text = "\n\n".join(buffer_parts).strip()
        if text:
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    text=text,
                    page_start=buffer_pages[0] if buffer_pages else None,
                    page_end=buffer_pages[-1] if buffer_pages else None,
                )
            )
        buffer_parts, buffer_pages, buffer_len = [], [], 0

    for page in pages:
        text = page.text.strip()
        if page.page_number is None:
            header = ""
        else:
            header = f"--- Page {page.page_number} ---\n"
        body = header + text

        if len(body) > chunk_chars:
            flush()
            window_start = 0
            while window_start < len(body):
                window_end = min(window_start + chunk_chars, len(body))
                chunk_text = body[window_start:window_end].strip()
                if chunk_text:
                    chunks.append(
                        TextChunk(
                            index=len(chunks),
                            text=chunk_text,
                            page_start=page.page_number,
                            page_end=page.page_number,
                        )
                    )
                if window_end >= len(body):
                    break
                window_start = max(window_start + 1, window_end - overlap_chars)
            continue

        if buffer_len + len(body) + 2 > chunk_chars:
            flush()
        buffer_parts.append(body)
        buffer_len += len(body) + 2
        if page.page_number is not None:
            buffer_pages.append(page.page_number)
    flush()

    warnings: list[str] = []
    if not chunks:
        raise DocumentError("No usable text chunks were produced from this document.")
    if len(chunks) > max_chunks:
        warnings.append(
            f"The document produced {len(chunks)} chunks but the configured limit is {max_chunks}. "
            f"Only the first {max_chunks} chunks (roughly the first part of the document) were analyzed. "
            "Upload a smaller document or raise MAX_CHUNKS for full coverage."
        )
        chunks = chunks[:max_chunks]
    return chunks, warnings
