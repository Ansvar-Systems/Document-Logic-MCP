"""Query engine for document intelligence."""

import logging
from typing import List, Dict, Any
from .database import Database

logger = logging.getLogger(__name__)


class QueryEngine:
    """Natural language query interface for document truths."""

    def __init__(self, db: Database):
        """Initialize with database."""
        self.db = db

    async def query(self, natural_language_query: str) -> List[Dict[str, Any]]:
        """
        Query documents with natural language.

        Returns structured truths with full metadata.
        Uses broad matching - returns MORE rather than filtering aggressively.
        """
        # Simple keyword-based search for now
        # TODO: Add semantic search with embeddings

        keywords = natural_language_query.lower().split()

        results = []

        async with self.db.connection() as conn:
            # Search truths by keywords
            for keyword in keywords:
                cursor = await conn.execute("""
                    SELECT
                        t.truth_id,
                        t.statement,
                        t.source_section,
                        t.source_page,
                        t.source_paragraph,
                        t.statement_type,
                        t.confidence,
                        t.source_authority,
                        d.filename,
                        d.document_date
                    FROM truths t
                    JOIN documents d ON t.doc_id = d.doc_id
                    WHERE LOWER(t.statement) LIKE ?
                    ORDER BY t.confidence DESC
                """, (f"%{keyword}%",))

                rows = await cursor.fetchall()

                for row in rows:
                    # Get related entities
                    entity_cursor = await conn.execute("""
                        SELECT e.entity_name
                        FROM truth_entities te
                        JOIN entities e ON te.entity_id = e.entity_id
                        WHERE te.truth_id = ?
                    """, (row["truth_id"],))

                    entities = [e["entity_name"] for e in await entity_cursor.fetchall()]

                    result = {
                        "truth_id": row["truth_id"],
                        "statement": row["statement"],
                        "source": {
                            "document": row["filename"],
                            "section": row["source_section"],
                            "page": row["source_page"],
                            "paragraph": row["source_paragraph"],
                        },
                        "document_date": row["document_date"],
                        "statement_type": row["statement_type"],
                        "confidence": row["confidence"],
                        "source_authority": row["source_authority"],
                        "related_entities": entities,
                    }

                    # Avoid duplicates
                    if result not in results:
                        results.append(result)

        logger.info(f"Query '{natural_language_query}' returned {len(results)} results")

        return results

    async def get_entity_aliases(self, entity_name: str) -> Dict[str, Any]:
        """Get potential aliases for an entity."""
        async with self.db.connection() as conn:
            # Find entity
            cursor = await conn.execute(
                "SELECT entity_id FROM entities WHERE entity_name = ? LIMIT 1",
                (entity_name,)
            )
            row = await cursor.fetchone()

            if not row:
                return {"entity": entity_name, "potential_aliases": [], "definitely_not": []}

            entity_id = row["entity_id"]

            # Get potential aliases
            alias_cursor = await conn.execute("""
                SELECT e.entity_name, ea.confidence, ea.evidence
                FROM entity_aliases ea
                JOIN entities e ON ea.entity_b_id = e.entity_id
                WHERE ea.entity_a_id = ? AND ea.relationship_type = 'potential_alias'
                ORDER BY ea.confidence DESC
            """, (entity_id,))

            potential = [
                {"entity": row["entity_name"], "confidence": row["confidence"], "evidence": row["evidence"]}
                for row in await alias_cursor.fetchall()
            ]

            # Get definitely_not
            not_cursor = await conn.execute("""
                SELECT e.entity_name, ea.evidence
                FROM entity_aliases ea
                JOIN entities e ON ea.entity_b_id = e.entity_id
                WHERE ea.entity_a_id = ? AND ea.relationship_type = 'definitely_not'
            """, (entity_id,))

            not_aliases = [
                {"entity": row["entity_name"], "evidence": row["evidence"]}
                for row in await not_cursor.fetchall()
            ]

            return {
                "entity": entity_name,
                "potential_aliases": potential,
                "definitely_not": not_aliases,
            }
