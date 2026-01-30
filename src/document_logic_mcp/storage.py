"""Storage layer for extraction results."""

import uuid
import logging
from typing import List, Optional
from .database import Database
from .extraction.schemas import (
    ExtractedTruth,
    ExtractedEntity,
    ExtractedRelationship,
    SourceAuthority,
)
from .embeddings import EmbeddingService

logger = logging.getLogger(__name__)


class ExtractionStorage:
    """Store extraction results in database."""

    def __init__(self, db: Database, embedding_service: Optional[EmbeddingService] = None):
        """
        Initialize with database and optional embedding service.

        Args:
            db: Database instance
            embedding_service: Optional embedding service for semantic search.
                              If None, embeddings won't be generated.
        """
        self.db = db
        self.embedding_service = embedding_service

    async def store_truths(
        self,
        doc_id: str,
        truths: List[ExtractedTruth],
        source_authority: SourceAuthority = SourceAuthority.HIGH
    ):
        """Store extracted truths with optional embeddings."""
        # Generate embeddings for batch efficiency
        embeddings = []
        if self.embedding_service:
            try:
                statements = [truth.statement for truth in truths]
                embedding_vectors = self.embedding_service.embed_batch(statements)
                embeddings = [
                    self.embedding_service.serialize_embedding(vec)
                    for vec in embedding_vectors
                ]
                logger.info(f"Generated embeddings for {len(truths)} truths")
            except Exception as e:
                logger.warning(f"Failed to generate embeddings: {e}. Storing without embeddings.")
                embeddings = [None] * len(truths)
        else:
            embeddings = [None] * len(truths)

        async with self.db.connection() as conn:
            for truth, embedding_blob in zip(truths, embeddings):
                truth_id = str(uuid.uuid4())

                await conn.execute("""
                    INSERT INTO truths (
                        truth_id, doc_id, statement, source_section,
                        source_page, source_paragraph, statement_type,
                        confidence, source_authority, embedding
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    truth_id,
                    doc_id,
                    truth.statement,
                    truth.section,
                    truth.page,
                    truth.paragraph,
                    truth.statement_type.value,
                    truth.confidence,
                    source_authority.value,
                    embedding_blob
                ))

                # Store truth-entity relationships
                for entity_name in truth.entities:
                    # Find or create entity
                    cursor = await conn.execute(
                        "SELECT entity_id FROM entities WHERE entity_name = ? AND doc_id = ?",
                        (entity_name, doc_id)
                    )
                    row = await cursor.fetchone()

                    if row:
                        entity_id = row["entity_id"]
                    else:
                        entity_id = str(uuid.uuid4())
                        await conn.execute("""
                            INSERT INTO entities (
                                entity_id, entity_name, doc_id,
                                first_mention_section, first_mention_page,
                                mention_count
                            ) VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            entity_id,
                            entity_name,
                            doc_id,
                            truth.section,
                            truth.page,
                            1
                        ))

                    # Link truth to entity
                    await conn.execute(
                        "INSERT OR IGNORE INTO truth_entities (truth_id, entity_id) VALUES (?, ?)",
                        (truth_id, entity_id)
                    )

            await conn.commit()

        logger.info(f"Stored {len(truths)} truths for document {doc_id}")

    async def store_entities(self, doc_id: str, entities: List[ExtractedEntity]):
        """Store extracted entities."""
        async with self.db.connection() as conn:
            for entity in entities:
                # Check if entity already exists
                cursor = await conn.execute(
                    "SELECT entity_id FROM entities WHERE entity_name = ? AND doc_id = ?",
                    (entity.name, doc_id)
                )
                row = await cursor.fetchone()

                if not row:
                    entity_id = str(uuid.uuid4())
                    await conn.execute("""
                        INSERT INTO entities (
                            entity_id, entity_name, doc_id,
                            first_mention_section, entity_type, mention_count
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        entity_id,
                        entity.name,
                        doc_id,
                        "Overview",  # Default for overview entities
                        entity.entity_type,
                        1
                    ))

            await conn.commit()

        logger.info(f"Stored {len(entities)} entities for document {doc_id}")

    async def store_relationships(self, doc_id: str, relationships: List[ExtractedRelationship]):
        """Store entity relationships."""
        async with self.db.connection() as conn:
            for rel in relationships:
                # Find entity IDs
                cursor_a = await conn.execute(
                    "SELECT entity_id FROM entities WHERE entity_name = ? AND doc_id = ?",
                    (rel.entity_a, doc_id)
                )
                cursor_b = await conn.execute(
                    "SELECT entity_id FROM entities WHERE entity_name = ? AND doc_id = ?",
                    (rel.entity_b, doc_id)
                )

                row_a = await cursor_a.fetchone()
                row_b = await cursor_b.fetchone()

                if row_a and row_b:
                    relationship_id = str(uuid.uuid4())
                    await conn.execute("""
                        INSERT INTO relationships (
                            relationship_id, entity_a_id, relationship_type,
                            entity_b_id, source_doc_id, source_section, confidence
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        relationship_id,
                        row_a["entity_id"],
                        rel.relationship_type,
                        row_b["entity_id"],
                        doc_id,
                        rel.evidence[:200],  # Use evidence as source_section
                        rel.confidence
                    ))

            await conn.commit()

        logger.info(f"Stored {len(relationships)} relationships for document {doc_id}")
