"""Tests for export functionality."""

import pytest
import json
from document_logic_mcp.export import AssessmentExporter
from document_logic_mcp.database import Database


@pytest.mark.asyncio
async def test_export_json(tmp_path):
    """Test exporting assessment as JSON."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    await db.initialize()

    # Insert test data
    async with db.connection() as conn:
        await conn.execute("""
            INSERT INTO documents (doc_id, filename, upload_date, sections_count, status)
            VALUES (?, ?, ?, ?, ?)
        """, ("doc_001", "test.pdf", "2024-01-30T10:00:00", 1, "completed"))

        await conn.execute("""
            INSERT INTO truths (
                truth_id, doc_id, statement, source_section,
                source_page, statement_type, confidence, source_authority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ("truth_001", "doc_001", "Test truth", "Section 1", 1, "assertion", 0.9, "high"))
        await conn.commit()

    exporter = AssessmentExporter(db)
    output_path = tmp_path / "export.json"

    await exporter.export_json(output_path)

    assert output_path.exists()

    with open(output_path) as f:
        data = json.load(f)

    assert "assessment_id" in data
    assert "documents" in data
    assert "truths" in data
    assert len(data["truths"]) == 1
