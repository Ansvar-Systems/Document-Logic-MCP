"""Tests for database layer."""

import pytest
import aiosqlite
from pathlib import Path
from datetime import datetime

from document_logic_mcp.database import Database


@pytest.mark.asyncio
async def test_database_initialization(tmp_path: Path) -> None:
    """Test that database creates all required tables."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))

    await db.initialize()

    # Verify all tables exist
    async with aiosqlite.connect(str(db_path)) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cursor.fetchall()]

    expected_tables = [
        "documents",
        "entities",
        "entity_aliases",
        "relationships",
        "sections",
        "truth_entities",
        "truths",
    ]

    assert tables == expected_tables, f"Expected {expected_tables}, got {tables}"


@pytest.mark.asyncio
async def test_insert_document(tmp_path: Path) -> None:
    """Test inserting a document into the database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    await db.initialize()

    # Insert a test document
    doc_id = "test-doc-1"
    filename = "test.pdf"
    upload_date = datetime.now().isoformat()

    async with db.connection() as conn:
        await conn.execute(
            """
            INSERT INTO documents (doc_id, filename, document_date, upload_date, sections_count, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (doc_id, filename, None, upload_date, 5, "parsed"),
        )
        await conn.commit()

        # Verify document was inserted
        cursor = await conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,))
        row = await cursor.fetchone()

    assert row is not None
    assert row["doc_id"] == doc_id
    assert row["filename"] == filename
    assert row["sections_count"] == 5
    assert row["status"] == "parsed"
