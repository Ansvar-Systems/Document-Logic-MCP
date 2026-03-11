"""Database layer for Document Logic MCP."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Union

import aiosqlite


LEGACY_UNASSIGNED_ORG = "legacy_unassigned"


class Database:
    """SQLite database manager for Document Logic MCP."""

    def __init__(self, db_path: Union[str, Path]) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Create database schema with all tables and indexes."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode = DELETE")
            await db.execute("PRAGMA foreign_keys = ON")

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL DEFAULT 'legacy_unassigned',
                    owner_user_id TEXT,
                    scope TEXT NOT NULL DEFAULT 'organization',
                    filename TEXT NOT NULL,
                    document_date TEXT,
                    upload_date TEXT NOT NULL,
                    sections_count INTEGER NOT NULL,
                    page_count INTEGER DEFAULT 1,
                    status TEXT NOT NULL,
                    raw_text TEXT,
                    metadata TEXT
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sections (
                    section_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    section_index INTEGER NOT NULL,
                    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
                )
                """
            )

            await db.execute(
                """
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
                """
            )

            await db.execute(
                """
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
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS truth_entities (
                    truth_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    PRIMARY KEY (truth_id, entity_id),
                    FOREIGN KEY (truth_id) REFERENCES truths(truth_id),
                    FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
                )
                """
            )

            await db.execute(
                """
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
                """
            )

            await db.execute(
                """
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
                """
            )

            await self._migrate_documents_table(db)

            try:
                await db.execute("ALTER TABLE sections ADD COLUMN page_start INTEGER")
            except aiosqlite.OperationalError:
                pass

            await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_org_id ON documents(org_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_org_scope ON documents(org_id, scope)")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_org_owner_scope "
                "ON documents(org_id, owner_user_id, scope)"
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_truths_doc_id ON truths(doc_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_entities_doc_id ON entities(doc_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(entity_name)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_sections_doc_id ON sections(doc_id)")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_relationships_doc_id ON relationships(source_doc_id)"
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_truth_entities_truth ON truth_entities(truth_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_truth_entities_entity ON truth_entities(entity_id)")

            await db.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS truths_fts USING fts5(
                    truth_id UNINDEXED,
                    statement,
                    source_section,
                    content=truths,
                    content_rowid=rowid
                )
                """
            )

            await db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS truths_fts_insert AFTER INSERT ON truths BEGIN
                    INSERT INTO truths_fts(rowid, truth_id, statement, source_section)
                    VALUES (new.rowid, new.truth_id, new.statement, new.source_section);
                END
                """
            )
            await db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS truths_fts_delete AFTER DELETE ON truths BEGIN
                    INSERT INTO truths_fts(truths_fts, rowid, truth_id, statement, source_section)
                    VALUES ('delete', old.rowid, old.truth_id, old.statement, old.source_section);
                END
                """
            )
            await db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS truths_fts_update AFTER UPDATE ON truths BEGIN
                    INSERT INTO truths_fts(truths_fts, rowid, truth_id, statement, source_section)
                    VALUES ('delete', old.rowid, old.truth_id, old.statement, old.source_section);
                    INSERT INTO truths_fts(rowid, truth_id, statement, source_section)
                    VALUES (new.rowid, new.truth_id, new.statement, new.source_section);
                END
                """
            )

            await db.commit()

    async def _migrate_documents_table(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute("PRAGMA table_info(documents)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "org_id" not in columns:
            await db.execute(
                f"ALTER TABLE documents ADD COLUMN org_id TEXT NOT NULL DEFAULT '{LEGACY_UNASSIGNED_ORG}'"
            )
        if "owner_user_id" not in columns:
            await db.execute("ALTER TABLE documents ADD COLUMN owner_user_id TEXT")
        if "scope" not in columns:
            await db.execute(
                "ALTER TABLE documents ADD COLUMN scope TEXT NOT NULL DEFAULT 'organization'"
            )
        if "metadata" not in columns:
            await db.execute("ALTER TABLE documents ADD COLUMN metadata TEXT")
        if "page_count" not in columns:
            await db.execute("ALTER TABLE documents ADD COLUMN page_count INTEGER DEFAULT 1")

        await db.execute(
            "UPDATE documents SET org_id = ? WHERE org_id IS NULL OR TRIM(org_id) = ''",
            (LEGACY_UNASSIGNED_ORG,),
        )
        await db.execute(
            "UPDATE documents SET scope = 'organization' WHERE scope IS NULL OR TRIM(scope) = ''"
        )

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            db.row_factory = aiosqlite.Row
            yield db
