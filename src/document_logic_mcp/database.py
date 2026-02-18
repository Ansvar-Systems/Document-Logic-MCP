"""Database layer for Document Logic MCP."""

import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Union


class Database:
    """SQLite database manager for Document Logic MCP."""

    def __init__(self, db_path: Union[str, Path]) -> None:
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Create database schema with all tables and indexes."""
        async with aiosqlite.connect(self.db_path) as db:
            # Use DELETE journal mode for serverless/container compatibility
            # (WAL creates sidecar files that break in read-only or ephemeral filesystems)
            await db.execute("PRAGMA journal_mode = DELETE")
            await db.execute("PRAGMA foreign_keys = ON")
            # Documents table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    document_date TEXT,
                    upload_date TEXT NOT NULL,
                    sections_count INTEGER NOT NULL,
                    page_count INTEGER DEFAULT 1,
                    status TEXT NOT NULL,
                    raw_text TEXT,
                    metadata TEXT
                )
            """)

            # Add metadata column if it doesn't exist (migration for existing databases)
            try:
                await db.execute("ALTER TABLE documents ADD COLUMN metadata TEXT")
            except aiosqlite.OperationalError:
                pass  # Column already exists

            # Sections table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sections (
                    section_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    section_index INTEGER NOT NULL,
                    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
                )
            """)

            # Truths table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS truths (
                    truth_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    source_section TEXT NOT NULL,
                    source_page INTEGER,
                    source_paragraph INTEGER,
                    document_date TEXT,
                    statement_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source_authority TEXT NOT NULL,
                    embedding BLOB,
                    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
                )
            """)

            # Entities table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    entity_name TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    first_mention_section TEXT NOT NULL,
                    first_mention_page INTEGER,
                    entity_type TEXT,
                    mention_count INTEGER NOT NULL,
                    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
                )
            """)

            # Truth-Entity junction table (many-to-many)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS truth_entities (
                    truth_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    PRIMARY KEY (truth_id, entity_id),
                    FOREIGN KEY (truth_id) REFERENCES truths(truth_id),
                    FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
                )
            """)

            # Entity aliases table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS entity_aliases (
                    entity_a_id TEXT NOT NULL,
                    entity_b_id TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence TEXT NOT NULL,
                    relationship_type TEXT NOT NULL,
                    PRIMARY KEY (entity_a_id, entity_b_id),
                    FOREIGN KEY (entity_a_id) REFERENCES entities(entity_id),
                    FOREIGN KEY (entity_b_id) REFERENCES entities(entity_id)
                )
            """)

            # Relationships table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS relationships (
                    relationship_id TEXT PRIMARY KEY,
                    source_doc_id TEXT NOT NULL,
                    entity_a_id TEXT NOT NULL,
                    relationship_type TEXT NOT NULL,
                    entity_b_id TEXT NOT NULL,
                    source_section TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    FOREIGN KEY (source_doc_id) REFERENCES documents(doc_id),
                    FOREIGN KEY (entity_a_id) REFERENCES entities(entity_id),
                    FOREIGN KEY (entity_b_id) REFERENCES entities(entity_id)
                )
            """)

            # Migrate existing databases: add page_count if missing
            try:
                await db.execute(
                    "ALTER TABLE documents ADD COLUMN page_count INTEGER DEFAULT 1"
                )
            except Exception:
                pass  # Column already exists

            # Migrate existing databases: add page_start to sections if missing
            try:
                await db.execute(
                    "ALTER TABLE sections ADD COLUMN page_start INTEGER"
                )
            except Exception:
                pass  # Column already exists

            # Create indexes for common queries
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_truths_doc_id ON truths(doc_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_entities_doc_id ON entities(doc_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(entity_name)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sections_doc_id ON sections(doc_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_relationships_doc_id ON relationships(source_doc_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_truth_entities_truth ON truth_entities(truth_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_truth_entities_entity ON truth_entities(entity_id)"
            )

            # FTS5 virtual table for full-text search on truths
            await db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS truths_fts USING fts5(
                    truth_id UNINDEXED,
                    statement,
                    source_section,
                    content=truths,
                    content_rowid=rowid
                )
            """)

            # FTS5 triggers to keep the index in sync with the truths table
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS truths_fts_insert AFTER INSERT ON truths BEGIN
                    INSERT INTO truths_fts(rowid, truth_id, statement, source_section)
                    VALUES (new.rowid, new.truth_id, new.statement, new.source_section);
                END
            """)
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS truths_fts_delete AFTER DELETE ON truths BEGIN
                    INSERT INTO truths_fts(truths_fts, rowid, truth_id, statement, source_section)
                    VALUES ('delete', old.rowid, old.truth_id, old.statement, old.source_section);
                END
            """)
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS truths_fts_update AFTER UPDATE ON truths BEGIN
                    INSERT INTO truths_fts(truths_fts, rowid, truth_id, statement, source_section)
                    VALUES ('delete', old.rowid, old.truth_id, old.statement, old.source_section);
                    INSERT INTO truths_fts(rowid, truth_id, statement, source_section)
                    VALUES (new.rowid, new.truth_id, new.statement, new.source_section);
                END
            """)

            await db.commit()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Context manager for database connections.

        Yields:
            Database connection
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            db.row_factory = aiosqlite.Row
            yield db
