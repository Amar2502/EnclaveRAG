"""Text extraction and overlapping chunking utilities for ingestion."""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


def extract_text_from_upload(filename: str, content: bytes) -> str:
    """Extract UTF-8 text from supported .txt, .md, or .pdf uploads."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension '{ext}'. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(content))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        return "\n\n".join(p for p in pages if p)

    return content.decode("utf-8", errors="replace").strip()


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    """Split text into overlapping chunks, preferring paragraph or word boundaries."""
    cleaned = text.strip()
    if not cleaned:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")

    chunks: list[str] = []
    start = 0
    total_len = len(cleaned)

    while start < total_len:
        end = min(start + chunk_size, total_len)
        if end < total_len:
            # Prefer splitting on paragraph break, newline, or space near the window end.
            window = cleaned[start:end]
            for sep in ("\n\n", "\n", ". ", " "):
                idx = window.rfind(sep)
                if idx > chunk_size // 2:
                    end = start + idx + len(sep)
                    break

        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)

        if end >= total_len:
            break
        start = max(end - overlap, start + 1)

    return chunks
