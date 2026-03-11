"""Tests for query interface."""

import pytest

from document_logic_mcp.database import Database
from document_logic_mcp.query import QueryEngine


@pytest.mark.asyncio
async def test_query_truths_is_scoped_by_org_and_owner(tmp_path):
    """Queries must return only truths from documents visible to the caller."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    await db.initialize()

    async with db.connection() as conn:
        await conn.execute(
            """
            INSERT INTO documents (doc_id, org_id, owner_user_id, scope, filename, upload_date, sections_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("doc-own", "org-1", "user-1", "conversation", "own.pdf", "2024-01-30", 1, "completed"),
        )
        await conn.execute(
            """
            INSERT INTO documents (doc_id, org_id, owner_user_id, scope, filename, upload_date, sections_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("doc-other", "org-1", "user-2", "conversation", "other.pdf", "2024-01-30", 1, "completed"),
        )
        await conn.execute(
            """
            INSERT INTO documents (doc_id, org_id, scope, filename, upload_date, sections_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("doc-org", "org-1", "organization", "org.pdf", "2024-01-30", 1, "completed"),
        )
        await conn.execute(
            """
            INSERT INTO documents (doc_id, org_id, owner_user_id, scope, filename, upload_date, sections_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("doc-foreign", "org-2", "user-9", "conversation", "foreign.pdf", "2024-01-30", 1, "completed"),
        )
        for truth_id, doc_id, statement in (
            ("truth-own", "doc-own", "Own document uses AES-256 encryption"),
            ("truth-other", "doc-other", "Other user's document uses AES-128 encryption"),
            ("truth-org", "doc-org", "Organization policy requires MFA"),
            ("truth-foreign", "doc-foreign", "Foreign tenant document mentions encryption"),
        ):
            await conn.execute(
                """
                INSERT INTO truths (
                    truth_id, doc_id, statement, source_section,
                    source_page, statement_type, confidence, source_authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (truth_id, doc_id, statement, "Security", 5, "assertion", 0.95, "high"),
            )
        await conn.commit()

    query_engine = QueryEngine(db)
    results = await query_engine.query(
        "encryption MFA",
        org_id="org-1",
        user_id="user-1",
    )

    statements = {result["statement"] for result in results}
    assert "Own document uses AES-256 encryption" in statements
    assert "Organization policy requires MFA" in statements
    assert "Other user's document uses AES-128 encryption" not in statements
    assert "Foreign tenant document mentions encryption" not in statements
