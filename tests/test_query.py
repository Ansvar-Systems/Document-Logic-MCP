"""Tests for query interface."""

import pytest
from document_logic_mcp.query import QueryEngine
from document_logic_mcp.database import Database


@pytest.mark.asyncio
async def test_query_truths(tmp_path):
    """Test querying truths by natural language."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    await db.initialize()

    # Insert test data
    async with db.connection() as conn:
        await conn.execute("""
            INSERT INTO documents (doc_id, filename, upload_date, sections_count, status)
            VALUES (?, ?, ?, ?, ?)
        """, ("doc_001", "test.pdf", "2024-01-30", 1, "completed"))

        await conn.execute("""
            INSERT INTO truths (
                truth_id, doc_id, statement, source_section,
                source_page, statement_type, confidence, source_authority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "truth_001",
            "doc_001",
            "System uses AES-256 encryption for data at rest",
            "Security",
            5,
            "assertion",
            0.95,
            "high"
        ))
        await conn.commit()

    query_engine = QueryEngine(db)
    results = await query_engine.query("encryption")

    assert len(results) > 0
    assert "AES-256" in results[0]["statement"]
