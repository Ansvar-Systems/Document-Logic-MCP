"""Query engine for document intelligence."""

import re
import logging
from typing import List, Dict, Any, Optional
from .database import Database
from .embeddings import EmbeddingService, compute_similarities

logger = logging.getLogger(__name__)

# Characters with special meaning in FTS5 query syntax
_FTS5_SPECIAL = re.compile(r'["\'\*\(\)\-\+\:\^\~\;\{\}\[\]]')


def _sanitize_fts5_query(raw: str) -> str:
    """Sanitize user input for safe use in FTS5 MATCH queries.

    Strips FTS5 special characters and wraps each token in double quotes
    to prevent query syntax injection. Returns an OR-joined query.
    """
    cleaned = _FTS5_SPECIAL.sub(" ", raw)
    tokens = cleaned.split()
    if not tokens:
        return '""'
    # Quote each token and join with OR for broad matching
    return " OR ".join(f'"{token}"' for token in tokens[:20])  # Cap at 20 tokens


async def _batch_fetch_entities(conn, truth_ids: List[str]) -> Dict[str, List[str]]:
    """Batch-fetch entity names for a list of truth_ids (eliminates N+1 queries)."""
    entity_map: Dict[str, List[str]] = {tid: [] for tid in truth_ids}
    if not truth_ids:
        return entity_map
    placeholders = ",".join("?" for _ in truth_ids)
    cursor = await conn.execute(f"""
        SELECT te.truth_id, e.entity_name
        FROM truth_entities te
        JOIN entities e ON te.entity_id = e.entity_id
        WHERE te.truth_id IN ({placeholders})
    """, truth_ids)
    for row in await cursor.fetchall():
        entity_map[row["truth_id"]].append(row["entity_name"])
    return entity_map


class QueryEngine:
    """Natural language query interface for document truths."""

    def __init__(self, db: Database, embedding_service: Optional[EmbeddingService] = None):
        """
        Initialize with database and optional embedding service.

        Args:
            db: Database instance
            embedding_service: Optional embedding service for semantic search.
                              If None, falls back to FTS5/keyword-based search.
        """
        self.db = db
        self.embedding_service = embedding_service

    async def query(
        self,
        natural_language_query: str,
        top_k: int = 20,
        similarity_threshold: float = 0.3,
        doc_ids: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Query documents with natural language.

        Returns structured truths with full metadata.
        Uses broad matching - returns MORE rather than filtering aggressively.

        Args:
            natural_language_query: Natural language query string
            top_k: Maximum number of results to return (1-100)
            similarity_threshold: Minimum similarity score (0.0-1.0) for semantic search
            doc_ids: Optional list of document IDs to scope the search to

        Returns:
            List of truths with metadata, sorted by relevance
        """
        top_k = max(1, min(top_k, 100))

        # Try semantic search first if embedding service available
        if self.embedding_service:
            try:
                return await self._semantic_search(
                    natural_language_query, top_k, similarity_threshold, doc_ids=doc_ids
                )
            except Exception as e:
                logger.warning(f"Semantic search failed: {e}. Falling back to FTS search.")

        # Fallback to FTS5 full-text search
        return await self._fts_search(natural_language_query, top_k=top_k, doc_ids=doc_ids)

    async def _semantic_search(
        self,
        query: str,
        top_k: int,
        similarity_threshold: float,
        doc_ids: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """Semantic search using embeddings."""
        query_embedding = self.embedding_service.embed_text(query)

        results = []

        async with self.db.connection() as conn:
            sql = """
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
            """
            params: list = []
            if doc_ids:
                placeholders = ",".join("?" for _ in doc_ids)
                sql += f" AND t.doc_id IN ({placeholders})"
                params.extend(doc_ids)

            cursor = await conn.execute(sql, params)
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

                # Collect candidates above threshold
                candidates = []
                for similarity, row in zip(similarities, truth_data):
                    if similarity >= similarity_threshold:
                        candidates.append((similarity, row))

                # Sort by similarity descending, take top_k
                candidates.sort(key=lambda x: x[0], reverse=True)
                candidates = candidates[:top_k]

                # Batch-fetch entities for all matching truth_ids
                candidate_truth_ids = [row["truth_id"] for _, row in candidates]
                entity_map = await _batch_fetch_entities(conn, candidate_truth_ids)

                for similarity, row in candidates:
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
                        "related_entities": entity_map.get(row["truth_id"], []),
                    })

        logger.info(
            f"Semantic search for '{query}' returned {len(results)} results "
            f"(threshold: {similarity_threshold})"
        )

        return results

    async def _fts_search(
        self,
        query: str,
        top_k: int = 20,
        doc_ids: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """Full-text search using FTS5 MATCH with fallback to LIKE."""
        fts_query = _sanitize_fts5_query(query)
        results = []

        async with self.db.connection() as conn:
            # Try FTS5 first
            try:
                sql = """
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
                        d.document_date,
                        rank
                    FROM truths_fts
                    JOIN truths t ON truths_fts.truth_id = t.truth_id
                    JOIN documents d ON t.doc_id = d.doc_id
                    WHERE truths_fts MATCH ?
                """
                params: list = [fts_query]
                if doc_ids:
                    placeholders = ",".join("?" for _ in doc_ids)
                    sql += f" AND t.doc_id IN ({placeholders})"
                    params.extend(doc_ids)
                sql += " ORDER BY rank LIMIT ?"
                params.append(top_k)

                cursor = await conn.execute(sql, params)
                rows = await cursor.fetchall()
            except Exception as e:
                logger.warning(f"FTS5 search failed ({e}), falling back to LIKE")
                rows = await self._like_fallback(conn, query, doc_ids, top_k)

            if not rows:
                rows = await self._like_fallback(conn, query, doc_ids, top_k)

            # Batch-fetch entities
            truth_ids = [row["truth_id"] for row in rows]
            entity_map = await _batch_fetch_entities(conn, truth_ids)

            for row in rows:
                results.append({
                    "truth_id": row["truth_id"],
                    "statement": row["statement"],
                    "similarity": None,
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
                    "related_entities": entity_map.get(row["truth_id"], []),
                })

        logger.info(f"FTS search for '{query}' returned {len(results)} results")
        return results

    async def _like_fallback(self, conn, query: str, doc_ids, top_k: int):
        """LIKE-based fallback when FTS5 is not available or returns no results."""
        keywords = query.lower().split()[:10]
        if not keywords:
            return []

        # Build OR conditions for each keyword
        conditions = " OR ".join("LOWER(t.statement) LIKE ?" for _ in keywords)
        params: list = [f"%{kw}%" for kw in keywords]

        sql = f"""
            SELECT DISTINCT
                t.truth_id, t.statement, t.source_section,
                t.source_page, t.source_paragraph, t.statement_type,
                t.confidence, t.source_authority, d.filename, d.document_date
            FROM truths t
            JOIN documents d ON t.doc_id = d.doc_id
            WHERE ({conditions})
        """
        if doc_ids:
            placeholders = ",".join("?" for _ in doc_ids)
            sql += f" AND t.doc_id IN ({placeholders})"
            params.extend(doc_ids)
        sql += " ORDER BY t.confidence DESC LIMIT ?"
        params.append(top_k)

        cursor = await conn.execute(sql, params)
        return await cursor.fetchall()

    async def get_entity_aliases(self, entity_name: str) -> Dict[str, Any]:
        """Get potential aliases for an entity."""
        async with self.db.connection() as conn:
            cursor = await conn.execute(
                "SELECT entity_id FROM entities WHERE entity_name = ? LIMIT 1",
                (entity_name,)
            )
            row = await cursor.fetchone()

            if not row:
                return {"entity": entity_name, "potential_aliases": [], "definitely_not": []}

            entity_id = row["entity_id"]

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
