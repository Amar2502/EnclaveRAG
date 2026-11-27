"""Phase 2 unit tests: text extraction, boundary-aware chunking, and classification tags."""

import pytest

from app.ingestion.chunker import chunk_text, extract_text_from_upload
from app.ingestion.service import classification_tag_for


def test_chunk_text_handles_empty_and_invalid_params() -> None:
    """Empty text produces no chunks; invalid window args raise ValueError."""
    assert chunk_text("   \n\t ") == []

    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("hello", chunk_size=0)

    with pytest.raises(ValueError, match="overlap"):
        chunk_text("hello", chunk_size=100, overlap=100)


def test_chunk_text_preserves_overlap_and_splits_cleanly() -> None:
    """Long text splits into overlapping chunks without losing trailing content."""
    text = ("Alpha beta gamma delta. " * 40).strip()
    chunks = chunk_text(text, chunk_size=200, overlap=40)

    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert chunks[-1].endswith("Alpha beta gamma delta.")


def test_extract_text_from_upload_supported_and_rejected_extensions() -> None:
    """Supports .txt and .md UTF-8 extraction; rejects unsupported binary types."""
    assert extract_text_from_upload("notes.md", b"# Heading\n\nBody") == "# Heading\n\nBody"
    assert extract_text_from_upload("notes.txt", b"  Plain text  ") == "Plain text"

    with pytest.raises(ValueError, match="Unsupported file extension"):
        extract_text_from_upload("malware.exe", b"MZ")


def test_classification_tag_for_maps_valid_tiers() -> None:
    """Valid clearance levels 1..4 map to canonical tags."""
    assert classification_tag_for(1) == "L1_PUBLIC"
    assert classification_tag_for(2) == "L2_INTERNAL"
    assert classification_tag_for(3) == "L3_CONFIDENTIAL"
    assert classification_tag_for(4) == "L4_EXECUTIVE"

    with pytest.raises(ValueError, match="clearance_level"):
        classification_tag_for(0)
