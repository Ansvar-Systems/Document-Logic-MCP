"""Tests for document parsers."""

import pytest
from pathlib import Path
from document_logic_mcp.parsers.pdf_parser import PDFParser
from document_logic_mcp.parsers.docx_parser import DOCXParser


@pytest.mark.skipif(
    not (Path(__file__).parent / "fixtures" / "sample.pdf").exists(),
    reason="Test fixture not available"
)
def test_pdf_parser_extracts_text():
    """Test PDF parser extracts text and metadata."""
    pdf_path = Path(__file__).parent / "fixtures" / "sample.pdf"

    parser = PDFParser()
    result = parser.parse(pdf_path)

    assert result.filename == "sample.pdf"
    assert len(result.sections) > 0
    assert result.page_count > 0
    assert len(result.raw_text) > 0


def test_pdf_parser_instantiates():
    """Test PDF parser can be instantiated."""
    parser = PDFParser()
    assert parser is not None


def test_docx_parser_instantiates():
    """Test DOCX parser can be instantiated."""
    parser = DOCXParser()
    assert parser is not None
