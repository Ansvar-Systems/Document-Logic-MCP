"""Tests for MCP tools."""

import json

import pytest

pytestmark = pytest.mark.legacy

from document_logic_mcp.tools import get_document_tool, parse_document_tool


@pytest.mark.asyncio
async def test_parse_document_tool(tmp_path):
    """Test parse_document MCP tool."""
    # Create a minimal test file
    test_file = tmp_path / "test.unsupported"
    test_file.write_text("Test document content")

    db_path = tmp_path / "test.db"

    # Note: This will fail without proper parsers, but tests basic structure
    # Real testing requires proper PDF/DOCX files
    with pytest.raises(ValueError, match="Unsupported file type"):
        await parse_document_tool(
            file_path=str(test_file),
            db_path=db_path
        )


@pytest.mark.asyncio
async def test_get_document_tool_can_return_sections(tmp_path):
    """Document details can include canonical parsed sections."""
    test_file = tmp_path / "test.json"
    test_file.write_text(json.dumps({
        "titel": "Richtlijn Monitoring en Logging",
        "licentiebeheer": "Gebeurtenissen worden gelogd in de originele taal.",
    }))

    db_path = tmp_path / "test.db"
    parse_result = await parse_document_tool(
        file_path=str(test_file),
        db_path=db_path,
    )

    result = await get_document_tool(
        doc_id=parse_result["doc_id"],
        db_path=db_path,
        include_sections=True,
    )

    assert result["sections_count"] == 2
    assert len(result["sections"]) == 2
    assert result["sections"][0]["section_ref"] == "section-1"
    assert result["sections"][0]["title"] == "Titel"
    assert result["sections"][1]["content"] == "Gebeurtenissen worden gelogd in de originele taal."
