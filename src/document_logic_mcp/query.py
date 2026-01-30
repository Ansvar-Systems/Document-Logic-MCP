"""Query engine for document intelligence."""

import logging
from typing import List, Dict, Any, Optional
from .database import Database
from .embeddings import EmbeddingService, compute_similarities

logger = logging.getLogger(__name__)


class QueryEngine:
    """Natural language query interface for document truths."""

    def __init__(self, db: Database, embedding_service: Optional[EmbeddingService] = None):
        """
        Initialize with database and optional embedding service.

        Args:
            db: Database instance
            embedding_service: Optional embedding service for semantic search.
                              If None, falls back to keyword-based search.
        """
        self.db = db
        self.embedding_service = embedding_service

    async def query(
        self,
        natural_language_query: str,
        top_k: int = 20,
        similarity_threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Query documents with natural language.

        Returns structured truths with full metadata.
        Uses broad matching - returns MORE rather than filtering aggressively.

        Args:
            natural_language_query: Natural language query string
            top_k: Maximum number of results to return
            similarity_threshold: Minimum similarity score (0.0-1.0) for semantic search

        Returns:
            List of truths with metadata, sorted by relevance
        """
        # Try semantic search first if embedding service available
        if self.embedding_service:
            try:
                return await self._semantic_search(
                    natural_language_query, top_k, similarity_threshold
                )
            except Exception as e:
                logger.warning(f"Semantic search failed: {e}. Falling back to keyword search.")

        # Fallback to keyword search
        return await self._keyword_search(natural_language_query)

    async def _semantic_search(
        self,
        query: str,
        top_k: int,
        similarity_threshold: float
    ) -> List[Dict[str, Any]]:
        """Semantic search using embeddings."""
        # Embed query
        query_embedding = self.embedding_service.embed_text(query)

        results = []

        async with self.db.connection() as conn:
            # Fetch all truths with embeddings
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
                    t.embedding,
                    d.filename,
                    d.document_date
                FROM truths t
                JOIN documents d ON t.doc_id = d.doc_id
                WHERE t.embedding IS NOT NULL
            """)

            rows = await cursor.fetchall()

            # Compute similarities
            truth_embeddings = []
            truth_data = []

            for row in rows:
                embedding_blob = row["embedding"]
                if embedding_blob:
                    truth_embedding = self.embedding_service.deserialize_embedding(embedding_blob)
                    truth_embeddings.append(truth_embedding)
                    truth_data.append(row)

            if truth_embeddings:
                similarities = compute_similarities(query_embedding, truth_embeddings)

                # Filter by threshold and collect results
                for similarity, row in zip(similarities, truth_data):
                    if similarity >= similarity_threshold:
                        # Get related entities
                        entity_cursor = await conn.execute("""
                            SELECT e.entity_name
                            FROM truth_entities te
                            JOIN entities e ON te.entity_id = e.entity_id
                            WHERE te.truth_id = ?
                        """, (row["truth_id"],))

                        entities = [e["entity_name"] for e in await entity_cursor.fetchall()]

                        results.append({
                            "truth_id": row["truth_id"],
                            "statement": row["statement"],
                            "similarity": round(similarity, 3),
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
                        })

                # Sort by similarity descending
                results.sort(key=lambda x: x["similarity"], reverse=True)

                # Return top-k
                results = results[:top_k]

        logger.info(
            f"Semantic search for '{query}' returned {len(results)} results "
            f"(threshold: {similarity_threshold})"
        )

        return results

    async def _keyword_search(self, query: str) -> List[Dict[str, Any]]:
        """Fallback keyword-based search."""
        keywords = query.lower().split()
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

        logger.info(f"Keyword search for '{query}' returned {len(results)} results")

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
