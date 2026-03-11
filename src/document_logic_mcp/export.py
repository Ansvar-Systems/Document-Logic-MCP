"""Export assessment data in multiple formats."""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .database import Database

logger = logging.getLogger(__name__)


def _document_access_clause(alias: str, org_id: str, user_id: str | None) -> tuple[str, list[Any]]:
    clause = f"{alias}.org_id = ? AND ({alias}.scope = 'organization'"
    params: list[Any] = [org_id]
    if user_id:
        clause += f" OR ({alias}.scope = 'conversation' AND {alias}.owner_user_id = ?)"
        params.append(user_id)
    clause += ")"
    return clause, params


class AssessmentExporter:
    """Export document intelligence assessment for a caller's accessible documents."""

    def __init__(self, db: Database, *, org_id: str, user_id: str | None = None):
        self.db = db
        self.org_id = org_id
        self.user_id = user_id.strip() if user_id and user_id.strip() else None

    async def _accessible_doc_ids(self, conn) -> list[str]:
        access_clause, access_params = _document_access_clause("d", self.org_id, self.user_id)
        cursor = await conn.execute(
            f"SELECT d.doc_id FROM documents d WHERE {access_clause} ORDER BY d.upload_date ASC",
            access_params,
        )
        return [row["doc_id"] for row in await cursor.fetchall()]

    async def _collect_data(self) -> Dict[str, Any]:
        """Collect assessment data for documents visible to the caller."""
        data = {
            "assessment_id": str(uuid.uuid4()),
            "exported_at": datetime.now().isoformat(),
            "documents": [],
            "truths": [],
            "entities": [],
            "relationships": [],
            "potential_aliases": [],
            "extraction_metadata": {},
        }

        async with self.db.connection() as conn:
            access_clause, access_params = _document_access_clause("d", self.org_id, self.user_id)

            cursor = await conn.execute(
                f"""
                SELECT d.doc_id, d.filename, d.document_date, d.upload_date, d.sections_count, d.status
                FROM documents d
                WHERE {access_clause}
                ORDER BY d.upload_date DESC
                """,
                access_params,
            )
            for row in await cursor.fetchall():
                data["documents"].append(
                    {
                        "id": row["doc_id"],
                        "filename": row["filename"],
                        "document_date": row["document_date"],
                        "upload_date": row["upload_date"],
                        "sections_count": row["sections_count"],
                        "status": row["status"],
                    }
                )

            cursor = await conn.execute(
                f"""
                SELECT
                    t.truth_id, t.doc_id, t.statement, t.source_section,
                    t.source_page, t.source_paragraph, t.statement_type,
                    t.confidence, t.source_authority, d.filename, d.document_date
                FROM truths t
                JOIN documents d ON t.doc_id = d.doc_id
                WHERE {access_clause}
                """,
                access_params,
            )
            for row in await cursor.fetchall():
                truth_id = row["truth_id"]
                entity_cursor = await conn.execute(
                    """
                    SELECT e.entity_name
                    FROM truth_entities te
                    JOIN entities e ON te.entity_id = e.entity_id
                    WHERE te.truth_id = ?
                    """,
                    (truth_id,),
                )
                entities = [entity["entity_name"] for entity in await entity_cursor.fetchall()]
                data["truths"].append(
                    {
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
                )

            cursor = await conn.execute(
                f"""
                SELECT e.entity_id, e.entity_name, e.doc_id, e.entity_type, e.mention_count
                FROM entities e
                JOIN documents d ON e.doc_id = d.doc_id
                WHERE {access_clause}
                """,
                access_params,
            )
            for row in await cursor.fetchall():
                data["entities"].append(
                    {
                        "entity_id": row["entity_id"],
                        "entity_name": row["entity_name"],
                        "document_id": row["doc_id"],
                        "entity_type": row["entity_type"],
                        "mention_count": row["mention_count"],
                    }
                )

            cursor = await conn.execute(
                f"""
                SELECT
                    r.relationship_id,
                    ea.entity_name as entity_a,
                    r.relationship_type,
                    eb.entity_name as entity_b,
                    r.source_doc_id,
                    r.source_section,
                    r.confidence
                FROM relationships r
                JOIN entities ea ON r.entity_a_id = ea.entity_id
                JOIN entities eb ON r.entity_b_id = eb.entity_id
                JOIN documents d ON r.source_doc_id = d.doc_id
                WHERE {access_clause}
                """,
                access_params,
            )
            for row in await cursor.fetchall():
                data["relationships"].append(
                    {
                        "relationship_id": row["relationship_id"],
                        "entity_a": row["entity_a"],
                        "relationship_type": row["relationship_type"],
                        "entity_b": row["entity_b"],
                        "source_document_id": row["source_doc_id"],
                        "source_section": row["source_section"],
                        "confidence": row["confidence"],
                    }
                )

            alias_access_clause_a, alias_access_params_a = _document_access_clause("da", self.org_id, self.user_id)
            alias_access_clause_b, alias_access_params_b = _document_access_clause("db", self.org_id, self.user_id)
            cursor = await conn.execute(
                f"""
                SELECT
                    ea_alias.entity_name as entity_a,
                    eb_alias.entity_name as entity_b,
                    al.confidence,
                    al.evidence,
                    al.relationship_type
                FROM entity_aliases al
                JOIN entities ea_alias ON al.entity_a_id = ea_alias.entity_id
                JOIN entities eb_alias ON al.entity_b_id = eb_alias.entity_id
                JOIN documents da ON ea_alias.doc_id = da.doc_id
                JOIN documents db ON eb_alias.doc_id = db.doc_id
                WHERE {alias_access_clause_a}
                  AND {alias_access_clause_b}
                """,
                [*alias_access_params_a, *alias_access_params_b],
            )
            for row in await cursor.fetchall():
                data["potential_aliases"].append(
                    {
                        "entity_a": row["entity_a"],
                        "entity_b": row["entity_b"],
                        "confidence": row["confidence"],
                        "evidence": row["evidence"],
                        "relationship_type": row["relationship_type"],
                    }
                )

            data["extraction_metadata"] = {
                "model_used": os.getenv("EXTRACTION_MODEL", "claude-sonnet-4-20250514"),
                "extraction_date": datetime.now().isoformat(),
                "documents_processed": len(data["documents"]),
                "truths_extracted": len(data["truths"]),
                "entities_found": len(data["entities"]),
                "relationships_found": len(data["relationships"]),
            }

        return data

    async def export_json(self, output_path: Path) -> Path:
        """Export the accessible assessment data as JSON."""
        data = await self._collect_data()

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as handle:
            json.dump(data, handle, indent=2)

        logger.info("Exported assessment to %s", output_path)
        return output_path

    async def export_sqlite(self, output_path: Path) -> Path:
        """Export the accessible assessment data as a filtered SQLite database."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()

        target_db = Database(output_path)
        await target_db.initialize()

        async with self.db.connection() as source, target_db.connection() as dest:
            doc_ids = await self._accessible_doc_ids(source)
            if not doc_ids:
                await dest.commit()
                logger.info("Exported empty filtered database to %s", output_path)
                return output_path

            placeholders = ",".join("?" for _ in doc_ids)

            async def _copy_rows(
                *,
                table: str,
                columns: list[str],
                where_clause: str,
                params: list[Any],
            ) -> None:
                cursor = await source.execute(
                    f"SELECT {', '.join(columns)} FROM {table} WHERE {where_clause}",
                    params,
                )
                rows = await cursor.fetchall()
                if not rows:
                    return
                insert_sql = (
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})"
                )
                await dest.executemany(
                    insert_sql,
                    [tuple(row[column] for column in columns) for row in rows],
                )

            await _copy_rows(
                table="documents",
                columns=[
                    "doc_id", "org_id", "owner_user_id", "scope", "filename",
                    "document_date", "upload_date", "sections_count", "page_count",
                    "status", "raw_text", "metadata",
                ],
                where_clause=f"doc_id IN ({placeholders})",
                params=doc_ids,
            )
            await _copy_rows(
                table="sections",
                columns=["section_id", "doc_id", "title", "content", "section_index", "page_start"],
                where_clause=f"doc_id IN ({placeholders})",
                params=doc_ids,
            )
            await _copy_rows(
                table="truths",
                columns=[
                    "truth_id", "doc_id", "statement", "source_section", "source_page",
                    "source_paragraph", "document_date", "statement_type", "confidence",
                    "source_authority", "embedding",
                ],
                where_clause=f"doc_id IN ({placeholders})",
                params=doc_ids,
            )
            await _copy_rows(
                table="entities",
                columns=[
                    "entity_id", "entity_name", "doc_id", "first_mention_section",
                    "first_mention_page", "entity_type", "mention_count",
                ],
                where_clause=f"doc_id IN ({placeholders})",
                params=doc_ids,
            )
            await _copy_rows(
                table="truth_entities",
                columns=["truth_id", "entity_id"],
                where_clause=(
                    f"truth_id IN (SELECT truth_id FROM truths WHERE doc_id IN ({placeholders}))"
                ),
                params=doc_ids,
            )
            await _copy_rows(
                table="relationships",
                columns=[
                    "relationship_id", "source_doc_id", "entity_a_id", "relationship_type",
                    "entity_b_id", "source_section", "confidence",
                ],
                where_clause=f"source_doc_id IN ({placeholders})",
                params=doc_ids,
            )
            await _copy_rows(
                table="entity_aliases",
                columns=["entity_a_id", "entity_b_id", "confidence", "evidence", "relationship_type"],
                where_clause=(
                    f"entity_a_id IN (SELECT entity_id FROM entities WHERE doc_id IN ({placeholders})) "
                    f"AND entity_b_id IN (SELECT entity_id FROM entities WHERE doc_id IN ({placeholders}))"
                ),
                params=[*doc_ids, *doc_ids],
            )

            await dest.commit()

        logger.info("Exported filtered database to %s", output_path)
        return output_path

    async def export_markdown(self, output_path: Path) -> Path:
        """Export the accessible assessment data as a Markdown report."""
        data = await self._collect_data()

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        md: list[str] = []
        md.append("# Document Intelligence Assessment")
        md.append(f"\n**Exported:** {data['exported_at']}")
        md.append(f"\n**Assessment ID:** {data['assessment_id']}")
        md.append("\n---\n")

        md.append(f"## Documents Processed ({len(data['documents'])})\n")
        for doc in data["documents"]:
            md.append(f"- **{doc['filename']}** ({doc['status']})")
            if doc["document_date"]:
                md.append(f"  - Date: {doc['document_date']}")
            md.append(f"  - Sections: {doc['sections_count']}")
        md.append("\n---\n")

        md.append(f"## Extracted Truths ({len(data['truths'])})\n")
        for doc in data["documents"]:
            doc_truths = [truth for truth in data["truths"] if truth["source"]["document"] == doc["filename"]]
            if not doc_truths:
                continue
            md.append(f"\n### {doc['filename']}\n")
            for truth in doc_truths:
                md.append(f"**{truth['statement_type'].upper()}** (confidence: {truth['confidence']:.0%})")
                md.append(f"\n> {truth['statement']}")
                md.append(f"\n*Source: {truth['source']['section']}, page {truth['source']['page']}*")
                if truth["related_entities"]:
                    md.append(f"\n*Entities: {', '.join(truth['related_entities'])}*")
                md.append("\n")

        md.append("\n---\n")

        md.append(f"## Entities ({len(data['entities'])})\n")
        for entity in sorted(data["entities"], key=lambda item: item["mention_count"], reverse=True):
            md.append(f"- **{entity['entity_name']}**")
            if entity["entity_type"]:
                md.append(f" ({entity['entity_type']})")
            md.append(f" - mentioned {entity['mention_count']} time(s)")

        md.append("\n---\n")

        meta = data["extraction_metadata"]
        md.append("## Extraction Metadata\n")
        md.append(f"- **Model:** {meta['model_used']}")
        md.append(f"- **Date:** {meta['extraction_date']}")
        md.append(f"- **Documents:** {meta['documents_processed']}")
        md.append(f"- **Truths:** {meta['truths_extracted']}")
        md.append(f"- **Entities:** {meta['entities_found']}")
        md.append(f"- **Relationships:** {meta['relationships_found']}")

        with open(output_path, "w") as handle:
            handle.write("\n".join(md))

        logger.info("Exported markdown to %s", output_path)
        return output_path
