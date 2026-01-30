"""Tests for extraction storage."""

import pytest
from document_logic_mcp.storage import ExtractionStorage
from document_logic_mcp.extraction.schemas import (
    ExtractedTruth,
    ExtractedEntity,
    StatementType,
)


@pytest.mark.asyncio
async def test_store_truths(tmp_path):
    """Test storing extracted truths."""
    from document_logic_mcp.database import Database

    db_path = tmp_path / "test.db"
    db = Database(db_path)
    await db.initialize()

    # Create test document
    async with db.connection() as conn:
        await conn.execute("""
            INSERT INTO documents (doc_id, filename, upload_date, sections_count, status)
            VALUES (?, ?, ?, ?, ?)
        """, ("doc_001", "test.pdf", "2024-01-30", 1, "extracting"))
        await conn.commit()

    storage = ExtractionStorage(db)

    truths = [
        ExtractedTruth(
            statement="System uses AES-256 encryption",
            section="Security",
            page=5,
            paragraph=2,
            statement_type=StatementType.ASSERTION,
            confidence=0.95,
            entities=["AES-256", "encryption"]
        )
    ]

    await storage.store_truths("doc_001", truths)

    # Verify stored
    async with db.connection() as conn:
        cursor = await conn.execute("SELECT COUNT(*) as count FROM truths WHERE doc_id = ?", ("doc_001",))
        count = (await cursor.fetchone())["count"]

    assert count == 1
