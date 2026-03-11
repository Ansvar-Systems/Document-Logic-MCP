"""Tests for export functionality."""

import json

import pytest

from document_logic_mcp.database import Database
from document_logic_mcp.export import AssessmentExporter


@pytest.mark.asyncio
async def test_export_json_only_includes_accessible_documents(tmp_path):
    """Exports must respect org and conversation ownership boundaries."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    await db.initialize()

    async with db.connection() as conn:
        await conn.execute(
            """
            INSERT INTO documents (doc_id, org_id, owner_user_id, scope, filename, upload_date, sections_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("doc-own", "org-1", "user-1", "conversation", "own.pdf", "2024-01-30T10:00:00", 1, "completed"),
        )
        await conn.execute(
            """
            INSERT INTO documents (doc_id, org_id, owner_user_id, scope, filename, upload_date, sections_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("doc-other", "org-1", "user-2", "conversation", "other.pdf", "2024-01-30T10:00:00", 1, "completed"),
        )
        await conn.execute(
            """
            INSERT INTO documents (doc_id, org_id, scope, filename, upload_date, sections_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("doc-org", "org-1", "organization", "policy.pdf", "2024-01-30T10:00:00", 1, "completed"),
        )

        for truth_id, doc_id, statement in (
            ("truth-own", "doc-own", "Own truth"),
            ("truth-other", "doc-other", "Other truth"),
            ("truth-org", "doc-org", "Org truth"),
        ):
            await conn.execute(
                """
                INSERT INTO truths (
                    truth_id, doc_id, statement, source_section,
                    source_page, statement_type, confidence, source_authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (truth_id, doc_id, statement, "Section 1", 1, "assertion", 0.9, "high"),
            )
        await conn.commit()

    exporter = AssessmentExporter(db, org_id="org-1", user_id="user-1")
    output_path = tmp_path / "export.json"
    await exporter.export_json(output_path)

    with open(output_path) as handle:
        data = json.load(handle)

    filenames = {doc["filename"] for doc in data["documents"]}
    truths = {truth["statement"] for truth in data["truths"]}

    assert filenames == {"own.pdf", "policy.pdf"}
    assert truths == {"Own truth", "Org truth"}
