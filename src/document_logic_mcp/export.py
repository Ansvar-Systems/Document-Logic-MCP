"""Export assessment data in multiple formats."""

import json
import logging
import shutil
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
from .database import Database

logger = logging.getLogger(__name__)


class AssessmentExporter:
    """Export document intelligence assessment."""

    def __init__(self, db: Database):
        """Initialize with database."""
        self.db = db

    async def _collect_data(self) -> Dict[str, Any]:
        """Collect all assessment data."""
        data = {
            "assessment_id": str(uuid.uuid4()),
            "exported_at": datetime.now().isoformat(),
            "documents": [],
            "truths": [],
            "entities": [],
            "relationships": [],
            "potential_aliases": [],
            "extraction_metadata": {}
        }

        async with self.db.connection() as conn:
            # Get documents
            cursor = await conn.execute("""
                SELECT doc_id, filename, document_date, upload_date, sections_count, status
                FROM documents
            """)

            for row in await cursor.fetchall():
                data["documents"].append({
                    "id": row["doc_id"],
                    "filename": row["filename"],
                    "document_date": row["document_date"],
                    "upload_date": row["upload_date"],
                    "sections_count": row["sections_count"],
                    "status": row["status"]
                })

            # Get truths
            cursor = await conn.execute("""
                SELECT
                    t.truth_id, t.doc_id, t.statement, t.source_section,
                    t.source_page, t.source_paragraph, t.statement_type,
                    t.confidence, t.source_authority, d.filename, d.document_date
                FROM truths t
                JOIN documents d ON t.doc_id = d.doc_id
            """)

            for row in await cursor.fetchall():
                truth_id = row["truth_id"]

                # Get related entities
                entity_cursor = await conn.execute("""
                    SELECT e.entity_name
                    FROM truth_entities te
                    JOIN entities e ON te.entity_id = e.entity_id
                    WHERE te.truth_id = ?
                """, (truth_id,))

                entities = [e["entity_name"] for e in await entity_cursor.fetchall()]

                data["truths"].append({
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
                    "related_entities": entities
                })

            # Get entities
            cursor = await conn.execute("""
                SELECT entity_id, entity_name, doc_id, entity_type, mention_count
                FROM entities
            """)

            for row in await cursor.fetchall():
                data["entities"].append({
                    "entity_id": row["entity_id"],
                    "entity_name": row["entity_name"],
                    "document_id": row["doc_id"],
                    "entity_type": row["entity_type"],
                    "mention_count": row["mention_count"]
                })

            # Get relationships
            cursor = await conn.execute("""
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
            """)

            for row in await cursor.fetchall():
                data["relationships"].append({
                    "relationship_id": row["relationship_id"],
                    "entity_a": row["entity_a"],
                    "relationship_type": row["relationship_type"],
                    "entity_b": row["entity_b"],
                    "source_document_id": row["source_doc_id"],
                    "source_section": row["source_section"],
                    "confidence": row["confidence"]
                })

            # Get entity aliases
            cursor = await conn.execute("""
                SELECT
                    ea_alias.entity_name as entity_a,
                    eb_alias.entity_name as entity_b,
                    al.confidence,
                    al.evidence,
                    al.relationship_type
                FROM entity_aliases al
                JOIN entities ea_alias ON al.entity_a_id = ea_alias.entity_id
                JOIN entities eb_alias ON al.entity_b_id = eb_alias.entity_id
            """)

            for row in await cursor.fetchall():
                data["potential_aliases"].append({
                    "entity_a": row["entity_a"],
                    "entity_b": row["entity_b"],
                    "confidence": row["confidence"],
                    "evidence": row["evidence"],
                    "relationship_type": row["relationship_type"]
                })

            # Metadata
            data["extraction_metadata"] = {
                "model_used": "claude-sonnet-4-20250514",
                "extraction_date": datetime.now().isoformat(),
                "documents_processed": len(data["documents"]),
                "truths_extracted": len(data["truths"]),
                "entities_found": len(data["entities"]),
                "relationships_found": len(data["relationships"])
            }

        return data

    async def export_json(self, output_path: Path) -> Path:
        """Export as JSON."""
        data = await self._collect_data()

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"Exported assessment to {output_path}")
        return output_path

    async def export_sqlite(self, output_path: Path) -> Path:
        """Export as SQLite database."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy database file
        shutil.copy2(self.db.db_path, output_path)

        logger.info(f"Exported database to {output_path}")
        return output_path

    async def export_markdown(self, output_path: Path) -> Path:
        """Export as Markdown report."""
        data = await self._collect_data()

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        md = []
        md.append(f"# Document Intelligence Assessment")
        md.append(f"\n**Exported:** {data['exported_at']}")
        md.append(f"\n**Assessment ID:** {data['assessment_id']}")
        md.append(f"\n---\n")

        # Documents
        md.append(f"## Documents Processed ({len(data['documents'])})\n")
        for doc in data["documents"]:
            md.append(f"- **{doc['filename']}** ({doc['status']})")
            if doc['document_date']:
                md.append(f"  - Date: {doc['document_date']}")
            md.append(f"  - Sections: {doc['sections_count']}")
        md.append("\n---\n")

        # Truths by document
        md.append(f"## Extracted Truths ({len(data['truths'])})\n")

        for doc in data["documents"]:
            doc_truths = [t for t in data["truths"] if t["source"]["document"] == doc["filename"]]
            if doc_truths:
                md.append(f"\n### {doc['filename']}\n")

                for truth in doc_truths:
                    md.append(f"**{truth['statement_type'].upper()}** (confidence: {truth['confidence']:.0%})")
                    md.append(f"\n> {truth['statement']}")
                    md.append(f"\n*Source: {truth['source']['section']}, page {truth['source']['page']}*")
                    if truth['related_entities']:
                        md.append(f"\n*Entities: {', '.join(truth['related_entities'])}*")
                    md.append("\n")

        md.append("\n---\n")

        # Entities
        md.append(f"## Entities ({len(data['entities'])})\n")
        for entity in sorted(data["entities"], key=lambda e: e['mention_count'], reverse=True):
            md.append(f"- **{entity['entity_name']}**")
            if entity['entity_type']:
                md.append(f" ({entity['entity_type']})")
            md.append(f" - mentioned {entity['mention_count']} time(s)")

        md.append("\n---\n")

        # Metadata
        meta = data["extraction_metadata"]
        md.append(f"## Extraction Metadata\n")
        md.append(f"- **Model:** {meta['model_used']}")
        md.append(f"- **Date:** {meta['extraction_date']}")
        md.append(f"- **Documents:** {meta['documents_processed']}")
        md.append(f"- **Truths:** {meta['truths_extracted']}")
        md.append(f"- **Entities:** {meta['entities_found']}")
        md.append(f"- **Relationships:** {meta['relationships_found']}")

        with open(output_path, 'w') as f:
            f.write('\n'.join(md))

        logger.info(f"Exported markdown to {output_path}")
        return output_path
