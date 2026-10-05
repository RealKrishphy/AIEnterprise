import io
import zipfile

import pytest
from fastapi import HTTPException

from lumen.documents import _safe_filename, validate_upload
from lumen.ingestion import chunk_text, clean_text, extract_text


def test_filename_is_normalized_without_path_components():
    assert _safe_filename("../../private report.txt") == "private report.txt"


def test_upload_validation_checks_extension_type_and_content():
    assert validate_upload("notes.txt", "text/plain", b"Hello") == ".txt"
    with pytest.raises(HTTPException) as mismatch:
        validate_upload("notes.pdf", "text/plain", b"%PDF-1.7")
    assert mismatch.value.status_code == 415
    with pytest.raises(HTTPException):
        validate_upload("notes.pdf", "application/pdf", b"not pdf")


def test_docx_validation_rejects_zip_without_word_document():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
    with pytest.raises(HTTPException):
        validate_upload(
            "notes.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            stream.getvalue(),
        )


def test_cleaning_and_heading_aware_overlapping_chunks():
    cleaned = clean_text("# Alpha\n\n" + "one two three four five " * 3 + "\n\n# Beta\n\nend")
    chunks = chunk_text(cleaned, max_words=6, overlap_words=2)
    assert chunks[0].heading == "Alpha"
    assert chunks[-1].heading == "Beta"
    assert chunks[0].content.split()[-2:] == chunks[1].content.split()[:2]
    assert "end" in chunks[-1].content


def test_exact_chunk_boundary_does_not_emit_overlap_only_duplicate():
    chunks = chunk_text("one two three four", max_words=4, overlap_words=1)
    assert len(chunks) == 1
    assert chunks[0].content == "one two three four"


def test_plaintext_extraction():
    assert extract_text("notes.md", b"# Topic\n\nText") == "# Topic\n\nText"
