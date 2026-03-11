"""Tests for input validation, security controls, and FTS5 search."""

import pytest
from unittest.mock import patch

from document_logic_mcp.database import Database
from document_logic_mcp.query import QueryEngine, _sanitize_fts5_query
from document_logic_mcp.tools import parse_document_tool, _validate_file_path


# --- FTS5 sanitization ---

class TestFTS5Sanitization:
    """Test FTS5 query sanitization prevents syntax injection."""

    def test_normal_query_preserved(self):
        result = _sanitize_fts5_query("encryption methods")
        assert '"encryption"' in result
        assert '"methods"' in result

    def test_special_chars_stripped(self):
        result = _sanitize_fts5_query('test" OR "hack')
        # Quotes and special chars must be stripped
        assert '""' not in result or result == '""'
        # Should not contain raw unquoted OR (which is FTS5 syntax)
        assert "hack" in result

    def test_fts5_operators_stripped(self):
        result = _sanitize_fts5_query("NOT encryption AND -secret")
        # The minus and special operators should be stripped
        assert "-" not in result

    def test_empty_query_returns_safe_default(self):
        result = _sanitize_fts5_query("")
        assert result == '""'

    def test_token_limit_caps_at_20(self):
        long_query = " ".join(f"word{i}" for i in range(30))
        result = _sanitize_fts5_query(long_query)
        # Should have at most 20 quoted tokens joined by OR
        token_count = result.count('" OR "') + 1
        assert token_count <= 20

    def test_sql_injection_attempt_neutralized(self):
        result = _sanitize_fts5_query("'; DROP TABLE truths --")
        assert "DROP" not in result or '"DROP"' in result
        assert ";" not in result


# --- FTS5 search integration ---

class TestFTS5Search:
    """Test that FTS5 search works end-to-end."""

    @pytest.mark.asyncio
    async def test_fts5_search_returns_results(self, tmp_path):
        """FTS5 search should find truths inserted via triggers."""
        db = Database(tmp_path / "test.db")
        await db.initialize()

        async with db.connection() as conn:
            await conn.execute("""
                INSERT INTO documents (doc_id, filename, upload_date, sections_count, status)
                VALUES ('doc1', 'test.pdf', '2024-01-01', 1, 'completed')
            """)
            await conn.execute("""
                INSERT INTO truths (
                    truth_id, doc_id, statement, source_section,
                    source_page, statement_type, confidence, source_authority
                ) VALUES ('t1', 'doc1', 'System uses AES-256 encryption for data at rest',
                          'Security', 5, 'assertion', 0.95, 'high')
            """)
            await conn.commit()

        query_engine = QueryEngine(db)
        results = await query_engine.query("AES encryption", org_id="legacy_unassigned")

        assert len(results) > 0
        assert "AES-256" in results[0]["statement"]

    @pytest.mark.asyncio
    async def test_fts5_search_no_results(self, tmp_path):
        """FTS5 search for non-matching term should return empty."""
        db = Database(tmp_path / "test.db")
        await db.initialize()

        async with db.connection() as conn:
            await conn.execute("""
                INSERT INTO documents (doc_id, filename, upload_date, sections_count, status)
                VALUES ('doc1', 'test.pdf', '2024-01-01', 1, 'completed')
            """)
            await conn.execute("""
                INSERT INTO truths (
                    truth_id, doc_id, statement, source_section,
                    source_page, statement_type, confidence, source_authority
                ) VALUES ('t1', 'doc1', 'System uses AES-256 encryption',
                          'Security', 1, 'assertion', 0.9, 'high')
            """)
            await conn.commit()

        query_engine = QueryEngine(db)
        results = await query_engine.query("quantum computing blockchain", org_id="legacy_unassigned")

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_top_k_limits_results(self, tmp_path):
        """top_k should cap the number of returned results."""
        db = Database(tmp_path / "test.db")
        await db.initialize()

        async with db.connection() as conn:
            await conn.execute("""
                INSERT INTO documents (doc_id, filename, upload_date, sections_count, status)
                VALUES ('doc1', 'test.pdf', '2024-01-01', 1, 'completed')
            """)
            for i in range(10):
                await conn.execute("""
                    INSERT INTO truths (
                        truth_id, doc_id, statement, source_section,
                        source_page, statement_type, confidence, source_authority
                    ) VALUES (?, 'doc1', ?, 'Section', 1, 'assertion', 0.9, 'high')
                """, (f"t{i}", f"Encryption method {i} uses strong algorithms"))
            await conn.commit()

        query_engine = QueryEngine(db)
        results = await query_engine.query("encryption", org_id="legacy_unassigned", top_k=3)

        assert len(results) <= 3


# --- File validation ---

class TestFileValidation:
    """Test file path validation and security controls."""

    def test_file_not_found_raises(self, tmp_path):
        """Non-existent file should raise FileNotFoundError."""
        fake_path = tmp_path / "nonexistent.pdf"
        with pytest.raises(FileNotFoundError):
            _validate_file_path(fake_path)

    def test_file_too_large_raises(self, tmp_path):
        """Files exceeding MAX_FILE_SIZE should be rejected."""
        large_file = tmp_path / "large.pdf"
        # Create a file just over 1 MB
        large_file.write_bytes(b"x" * (1024 * 1024 + 1))

        with patch("document_logic_mcp.tools.MAX_FILE_SIZE", 1024 * 1024):
            with pytest.raises(ValueError, match="File too large"):
                _validate_file_path(large_file)

    def test_path_traversal_blocked(self, tmp_path):
        """Files outside ALLOWED_DOC_DIRS should be rejected."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        outside_file = tmp_path / "outside.pdf"
        outside_file.write_text("data")

        with patch("document_logic_mcp.tools.ALLOWED_DOC_DIRS", [allowed_dir]):
            with pytest.raises(ValueError, match="Access denied"):
                _validate_file_path(outside_file)

    def test_path_within_allowed_dir_passes(self, tmp_path):
        """Files inside ALLOWED_DOC_DIRS should pass validation."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        valid_file = allowed_dir / "doc.pdf"
        valid_file.write_text("data")

        with patch("document_logic_mcp.tools.ALLOWED_DOC_DIRS", [allowed_dir]):
            # Should not raise
            _validate_file_path(valid_file)

    @pytest.mark.asyncio
    async def test_unsupported_format_raises(self, tmp_path):
        """Unsupported file extensions should raise ValueError."""
        txt_file = tmp_path / "test.exe"
        txt_file.write_text("content")
        db_path = tmp_path / "test.db"

        with pytest.raises(ValueError, match="Unsupported file type"):
            await parse_document_tool(str(txt_file), db_path, org_id="org-1", owner_user_id="user-1")


# --- list_documents pagination ---

class TestListDocumentsPagination:
    """Test list_documents with limit/offset."""

    @pytest.mark.asyncio
    async def test_limit_caps_results(self, tmp_path):
        from document_logic_mcp.tools import list_documents_tool

        db = Database(tmp_path / "test.db")
        await db.initialize()

        async with db.connection() as conn:
            for i in range(5):
                await conn.execute("""
                    INSERT INTO documents (doc_id, filename, upload_date, sections_count, status)
                    VALUES (?, ?, '2024-01-01', 1, 'completed')
                """, (f"doc{i}", f"file{i}.pdf"))
            await conn.commit()

        result = await list_documents_tool(tmp_path / "test.db", org_id="legacy_unassigned", limit=2, offset=0)
        assert result["count"] == 2
        assert result["total"] == 5

    @pytest.mark.asyncio
    async def test_offset_skips_documents(self, tmp_path):
        from document_logic_mcp.tools import list_documents_tool

        db = Database(tmp_path / "test.db")
        await db.initialize()

        async with db.connection() as conn:
            for i in range(5):
                await conn.execute("""
                    INSERT INTO documents (doc_id, filename, upload_date, sections_count, status)
                    VALUES (?, ?, '2024-01-01', 1, 'completed')
                """, (f"doc{i}", f"file{i}.pdf"))
            await conn.commit()

        result = await list_documents_tool(tmp_path / "test.db", org_id="legacy_unassigned", limit=100, offset=3)
        assert result["count"] == 2  # 5 total, skip 3 = 2 remaining
        assert result["total"] == 5
