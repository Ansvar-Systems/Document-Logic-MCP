"""Tests for MCP tools."""

import pytest

from document_logic_mcp.database import Database
from document_logic_mcp.tools import parse_document_tool


@pytest.mark.asyncio
async def test_parse_document_tool_stores_tenant_scope(tmp_path):
    """Parsed documents must persist org, owner, and scope metadata."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Test document content")
    db_path = tmp_path / "test.db"

    result = await parse_document_tool(
        file_path=str(test_file),
        db_path=db_path,
        org_id="org-1",
        owner_user_id="user-1",
    )

    assert result["status"] == "parsed"

    db = Database(db_path)
    await db.initialize()
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT org_id, owner_user_id, scope, filename FROM documents WHERE doc_id = ?",
                (result["doc_id"],),
            )
        ).fetchone()

    assert row["org_id"] == "org-1"
    assert row["owner_user_id"] == "user-1"
    assert row["scope"] == "conversation"
    assert row["filename"] == "test.txt"


@pytest.mark.asyncio
async def test_parse_document_tool_requires_org_write_for_org_scope(tmp_path):
    test_file = tmp_path / "policy.txt"
    test_file.write_text("Organization document")

    with pytest.raises(PermissionError, match="allow_org_write"):
        await parse_document_tool(
            file_path=str(test_file),
            db_path=tmp_path / "test.db",
            org_id="org-1",
            scope="organization",
        )
