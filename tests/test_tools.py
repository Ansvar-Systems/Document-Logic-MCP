"""Tests for MCP tools."""

import pytest
from pathlib import Path
from document_logic_mcp.tools import parse_document_tool


@pytest.mark.asyncio
async def test_parse_document_tool(tmp_path):
    """Test parse_document MCP tool."""
    # Create a minimal test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("Test document content")

    db_path = tmp_path / "test.db"

    # Note: This will fail without proper parsers, but tests basic structure
    # Real testing requires proper PDF/DOCX files
    with pytest.raises(ValueError, match="Unsupported file type"):
        await parse_document_tool(
            file_path=str(test_file),
            db_path=db_path
        )
