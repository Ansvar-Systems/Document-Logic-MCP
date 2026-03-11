"""Query engine for document intelligence."""

import logging
import re
from typing import Any, Dict, List, Optional

from .database import Database
from .embeddings import EmbeddingService, compute_similarities

logger = logging.getLogger(__name__)

_FTS5_SPECIAL = re.compile(r'["\'\*\(\)\-\+\:\^\~\;\{\}\[\]]')


def _sanitize_fts5_query(raw: str) -> str:
    cleaned = _FTS5_SPECIAL.sub(" ", raw)
    tokens = cleaned.split()
    if not tokens:
        return '""'
    return " OR ".join(f'"{token}"' for token in tokens[:20])


def _document_access_clause(alias: str, org_id: str, user_id: str | None) -> tuple[str, list[Any]]:
    clause = f"{alias}.org_id = ? AND ({alias}.scope = 'organization'"
    params: list[Any] = [org_id]
    if user_id:
        clause += f" OR ({alias}.scope = 'conversation' AND {alias}.owner_user_id = ?)"
        params.append(user_id)
    clause += ")"
    return clause, params


async def _batch_fetch_entities(conn, truth_ids: List[str]) -> Dict[str, List[str]]:
    entity_map: Dict[str, List[str]] = {tid: [] for tid in truth_ids}
    if not truth_ids:
        return entity_map
    placeholders = ",".join("?" for _ in truth_ids)
    cursor = await conn.execute(
        f"""
        SELECT te.truth_id, e.entity_name
        FROM truth_entities te
        JOIN entities e ON te.entity_id = e.entity_id
        WHERE te.truth_id IN ({placeholders})
        """,
        truth_ids,
    )
    for row in await cursor.fetchall():
        entity_map[row["truth_id"]].append(row["entity_name"])
    return entity_map


class QueryEngine:
    """Natural language query interface for document truths."""

    def __init__(self, db: Database, embedding_service: Optional[EmbeddingService] = None):
        self.db = db
        self.embedding_service = embedding_service

    async def query(
        self,
        natural_language_query: str,
        *,
        org_id: str,
        user_id: str | None = None,
        top_k: int = 20,
        similarity_threshold: float = 0.3,
        doc_ids: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        top_k = max(1, min(top_k, 100))

        if self.embedding_service:
            try:
                return await self._semantic_search(
                    natural_language_query,
                    org_id=org_id,
                    user_id=user_id,
                    top_k=top_k,
                    similarity_threshold=similarity_threshold,
                    doc_ids=doc_ids,
                )
            except Exception as exc:
                logger.warning("Semantic search failed: %s. Falling back to FTS search.", exc)

        return await self._fts_search(
            natural_language_query,
            org_id=org_id,
            user_id=user_id,
            top_k=top_k,
            doc_ids=doc_ids,
        )

    async def _semantic_search(
        self,
        query: str,
        *,
        org_id: str,
        user_id: str | None,
        top_k: int,
        similarity_threshold: float,
        doc_ids: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        query_embedding = self.embedding_service.embed_text(query)
        access_clause, access_params = _document_access_clause("d", org_id, user_id)
        results = []

        async with self.db.connection() as conn:
            sql = f"""
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
                  AND {access_clause}
            """
            params: list[Any] = list(access_params)
            if doc_ids:
                placeholders = ",".join("?" for _ in doc_ids)
                sql += f" AND t.doc_id IN ({placeholders})"
                params.extend(doc_ids)

            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()

            truth_embeddings = []
            truth_data = []
            for row in rows:
                embedding_blob = row["embedding"]
                if embedding_blob:
                    truth_embeddings.append(
                        self.embedding_service.deserialize_embedding(embedding_blob)
                    )
                    truth_data.append(row)

            if truth_embeddings:
                similarities = compute_similarities(query_embedding, truth_embeddings)
                candidates = []
                for similarity, row in zip(similarities, truth_data):
                    if similarity >= similarity_threshold:
                        candidates.append((similarity, row))
                candidates.sort(key=lambda item: item[0], reverse=True)
                candidates = candidates[:top_k]

                entity_map = await _batch_fetch_entities(
                    conn,
                    [row["truth_id"] for _, row in candidates],
                )

                for similarity, row in candidates:
                    results.append(
                        {
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
                        }
                    )

        logger.info(
            "Semantic search for %r returned %d results (threshold=%s)",
            query,
            len(results),
            similarity_threshold,
        )
        return results

    async def _fts_search(
        self,
        query: str,
        *,
        org_id: str,
        user_id: str | None,
        top_k: int = 20,
        doc_ids: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        fts_query = _sanitize_fts5_query(query)
        access_clause, access_params = _document_access_clause("d", org_id, user_id)
        results = []

        async with self.db.connection() as conn:
            try:
                sql = f"""
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
                      AND {access_clause}
                """
                params: list[Any] = [fts_query, *access_params]
                if doc_ids:
                    placeholders = ",".join("?" for _ in doc_ids)
                    sql += f" AND t.doc_id IN ({placeholders})"
                    params.extend(doc_ids)
                sql += " ORDER BY rank LIMIT ?"
                params.append(top_k)

                cursor = await conn.execute(sql, params)
                rows = await cursor.fetchall()
            except Exception as exc:
                logger.warning("FTS5 search failed (%s), falling back to LIKE", exc)
                rows = await self._like_fallback(conn, query, org_id, user_id, doc_ids, top_k)

            if not rows:
                rows = await self._like_fallback(conn, query, org_id, user_id, doc_ids, top_k)

            entity_map = await _batch_fetch_entities(conn, [row["truth_id"] for row in rows])

            for row in rows:
                results.append(
                    {
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
                    }
                )

        logger.info("FTS search for %r returned %d results", query, len(results))
        return results

    async def _like_fallback(
        self,
        conn,
        query: str,
        org_id: str,
        user_id: str | None,
        doc_ids: List[str] | None,
        top_k: int,
    ):
        keywords = query.lower().split()[:10]
        if not keywords:
            return []

        conditions = " OR ".join("LOWER(t.statement) LIKE ?" for _ in keywords)
        params: list[Any] = [f"%{kw}%" for kw in keywords]
        access_clause, access_params = _document_access_clause("d", org_id, user_id)

        sql = f"""
            SELECT DISTINCT
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
            WHERE ({conditions})
              AND {access_clause}
        """
        params.extend(access_params)
        if doc_ids:
            placeholders = ",".join("?" for _ in doc_ids)
            sql += f" AND t.doc_id IN ({placeholders})"
            params.extend(doc_ids)
        sql += " ORDER BY t.confidence DESC LIMIT ?"
        params.append(top_k)

        cursor = await conn.execute(sql, params)
        return await cursor.fetchall()

    async def get_entity_aliases(
        self,
        entity_name: str,
        *,
        org_id: str,
        user_id: str | None = None,
    ) -> Dict[str, Any]:
        access_clause, access_params = _document_access_clause("d", org_id, user_id)

        async with self.db.connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT e.entity_id
                FROM entities e
                JOIN documents d ON e.doc_id = d.doc_id
                WHERE e.entity_name = ?
                  AND {access_clause}
                LIMIT 1
                """,
                [entity_name, *access_params],
            )
            row = await cursor.fetchone()

            if not row:
                return {"entity": entity_name, "potential_aliases": [], "definitely_not": []}

            entity_id = row["entity_id"]

            alias_cursor = await conn.execute(
                f"""
                SELECT eb.entity_name, ea.confidence, ea.evidence
                FROM entity_aliases ea
                JOIN entities eb ON ea.entity_b_id = eb.entity_id
                JOIN documents db ON eb.doc_id = db.doc_id
                WHERE ea.entity_a_id = ?
                  AND ea.relationship_type = 'potential_alias'
                  AND {_document_access_clause('db', org_id, user_id)[0]}
                ORDER BY ea.confidence DESC
                """,
                [entity_id, *_document_access_clause("db", org_id, user_id)[1]],
            )
            potential = [
                {
                    "entity": row["entity_name"],
                    "confidence": row["confidence"],
                    "evidence": row["evidence"],
                }
                for row in await alias_cursor.fetchall()
            ]

            not_cursor = await conn.execute(
                f"""
                SELECT eb.entity_name, ea.evidence
                FROM entity_aliases ea
                JOIN entities eb ON ea.entity_b_id = eb.entity_id
                JOIN documents db ON eb.doc_id = db.doc_id
                WHERE ea.entity_a_id = ?
                  AND ea.relationship_type = 'definitely_not'
                  AND {_document_access_clause('db', org_id, user_id)[0]}
                """,
                [entity_id, *_document_access_clause("db", org_id, user_id)[1]],
            )
            not_aliases = [
                {"entity": row["entity_name"], "evidence": row["evidence"]}
                for row in await not_cursor.fetchall()
            ]

            return {
                "entity": entity_name,
                "potential_aliases": potential,
                "definitely_not": not_aliases,
            }
