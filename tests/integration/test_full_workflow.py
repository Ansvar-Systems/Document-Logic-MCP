"""Integration test for full document processing workflow."""

import json
import pytest
from pathlib import Path
from document_logic_mcp.tools import parse_document_tool, extract_document_tool
from document_logic_mcp.query import QueryEngine
from document_logic_mcp.export import AssessmentExporter
from document_logic_mcp.database import Database


@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_document_workflow(tmp_path):
    """Test complete workflow: parse → extract → query → export."""
    db_path = tmp_path / "test.db"

    # Create test document as JSON (one of the supported formats)
    test_doc = tmp_path / "test_architecture.json"
    test_doc.write_text(json.dumps({
        "system_architecture": (
            "The system uses AES-256 encryption for all data at rest. "
            "Customer data is stored in the PostgreSQL database."
        ),
        "authentication": "Authentication is handled via OAuth 2.0.",
    }))

    # Step 1: Parse document
    parse_result = await parse_document_tool(
        file_path=str(test_doc),
        db_path=db_path
    )

    assert parse_result["status"] == "parsed"
    doc_id = parse_result["doc_id"]

    # Step 2: Extract (would call LLM in real scenario)
    # Skipping actual extraction in test due to LLM dependency

    # Step 3: Query (with manually inserted test data)
    db = Database(db_path)
    await db.initialize()

    async with db.connection() as conn:
        await conn.execute("""
            INSERT INTO truths (
                truth_id, doc_id, statement, source_section,
                source_page, statement_type, confidence, source_authority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "t1", doc_id,
            "System uses AES-256 encryption for all data at rest",
            "System Architecture", 1, "assertion", 0.95, "high"
        ))
        await conn.commit()

    query_engine = QueryEngine(db)
    results = await query_engine.query("encryption")

    assert len(results) > 0
    assert "AES-256" in results[0]["statement"]

    # Step 4: Export
    exporter = AssessmentExporter(db)
    export_path = tmp_path / "export.json"
    await exporter.export_json(export_path)

    assert export_path.exists()
