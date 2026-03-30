"""MCP tool implementations.

Tools:
- parse_document_tool: Fast, deterministic document parsing (seconds)
- extract_document_tool: LLM-based hierarchical extraction (minutes)
  - Pass 1: Document overview
  - Pass 2: Per-section truths/entities/relationships
  - Pass 3 (optional): Cross-section synthesis — activated by analysis_context
    Produces component registry, trust boundaries, implicit negatives, ambiguity flags

The analysis_context parameter enables domain-specific extraction intelligence.
See CONTEXT_SUPPLEMENTS in prompts.py for available contexts:
- "stride_threat_modeling": Trust boundaries, data flow directionality, implicit negatives
- "tprm_vendor_assessment": Certifications, subprocessors, SLAs, data residency
- "compliance_mapping": Obligations, deadlines, penalties, cross-references, scope definitions
"""

import logging
import os
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from .database import Database
from .parsers import (
    PDFParser, DOCXParser, JSONParser,
    TextParser, MarkdownParser, CSVParser,
    XLSXParser, PPTXParser, HTMLParser,
    ImageParser,
)
from .extraction import DocumentExtractor
from .resources import resolve_technology_name as _resolve_tech, suggest_terminology_addition as _suggest_term

logger = logging.getLogger(__name__)

# Maximum file size for parsing (default 50 MB)
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "50")) * 1024 * 1024

# Allowed directories for file access (colon-separated). Empty = allow all (dev mode).
_allowed_dirs_raw = os.getenv("ALLOWED_DOC_DIRS", "")
ALLOWED_DOC_DIRS = [Path(p).resolve() for p in _allowed_dirs_raw.split(":") if p.strip()] if _allowed_dirs_raw else []


def _validate_file_path(file_path: Path) -> None:
    """Validate that file_path is within allowed directories and not too large.

    Raises:
        ValueError: If path is outside allowed directories or file is too large.
        FileNotFoundError: If file does not exist.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path.name}")

    resolved = file_path.resolve()

    # Path traversal protection — only when ALLOWED_DOC_DIRS is configured
    if ALLOWED_DOC_DIRS:
        if not any(resolved == d or resolved.is_relative_to(d) for d in ALLOWED_DOC_DIRS):
            raise ValueError(
                "Access denied: file is outside allowed directories"
            )

    # File size check
    file_size = resolved.stat().st_size
    if file_size > MAX_FILE_SIZE:
        raise ValueError(
            f"File too large: {file_size / (1024*1024):.1f} MB "
            f"(max {MAX_FILE_SIZE / (1024*1024):.0f} MB)"
        )


async def parse_document_tool(file_path: str, db_path: Path) -> Dict[str, Any]:
    """
    Parse a document and store metadata.

    Fast (seconds), deterministic parsing of document structure.
    Returns document ID for use in extract_document.
    """
    file_path = Path(file_path)
    _validate_file_path(file_path)

    # Select parser based on extension
    suffix = file_path.suffix.lower()
    parser_map = {
        ".pdf": PDFParser,
        ".docx": DOCXParser,
        ".json": JSONParser,
        ".txt": TextParser,
        ".md": MarkdownParser,
        ".csv": CSVParser,
        ".xlsx": XLSXParser,
        ".pptx": PPTXParser,
        ".html": HTMLParser,
        ".htm": HTMLParser,
        ".png": ImageParser,
        ".jpg": ImageParser,
        ".jpeg": ImageParser,
        ".tiff": ImageParser,
        ".tif": ImageParser,
        ".bmp": ImageParser,
        ".gif": ImageParser,
        ".webp": ImageParser,
    }
    parser_cls = parser_map.get(suffix)
    if parser_cls is None:
        raise ValueError(f"Unsupported file type: {suffix}")
    parser = parser_cls()

    # Parse document
    logger.info(f"Parsing {file_path.name}...")
    parse_result = parser.parse(file_path)

    # Store in database
    db = Database(db_path)
    await db.initialize()

    doc_id = str(uuid.uuid4())

    async with db.connection() as conn:
        # Store document metadata
        import json
        metadata_json = json.dumps(parse_result.metadata) if parse_result.metadata else None

        await conn.execute("""
            INSERT INTO documents (doc_id, filename, upload_date, sections_count, page_count, status, raw_text, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            doc_id,
            parse_result.filename,
            datetime.now().isoformat(),
            len(parse_result.sections),
            parse_result.page_count,
            "parsed",
            parse_result.raw_text,
            metadata_json
        ))

        # Store sections
        for idx, section in enumerate(parse_result.sections):
            section_id = str(uuid.uuid4())
            await conn.execute("""
                INSERT INTO sections (
                    section_id, doc_id, title, content, section_index, page_start, page_end
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                section_id,
                doc_id,
                section.title,
                section.content,
                idx,
                section.page_start,
                section.page_end,
            ))

        await conn.commit()

    logger.info(f"Parsed {file_path.name}: {len(parse_result.sections)} sections")

    return {
        "doc_id": doc_id,
        "filename": parse_result.filename,
        "sections_count": len(parse_result.sections),
        "page_count": parse_result.page_count,
        "status": "parsed",
        "entities_preview": [s.title for s in parse_result.sections[:3]] if parse_result.sections else []
    }


async def extract_document_tool(
    doc_id: str,
    db_path: Path,
    extraction_model: str | None = None,
    analysis_context: Optional[str] = None,
    org_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract truths, entities, and relationships from parsed document.

    Slow (minutes), LLM-based hierarchical extraction.
    Blocks until complete - honest about wait time.

    Args:
        doc_id: Document ID from parse operation
        db_path: Path to SQLite database
        extraction_model: Optional model override (e.g., 'ollama/llama3.1')
        analysis_context: Optional domain context for enhanced extraction.
            When provided, activates:
            1. Domain-specific prompt supplements for per-section extraction (Pass 2)
            2. Cross-section synthesis pass (Pass 3) producing component registry,
               trust boundaries, implicit negatives, and ambiguity flags
            Available contexts: "stride_threat_modeling", "tprm_vendor_assessment", "compliance_mapping"
    """
    from .parsers.base import ParseResult, Section
    from .storage import ExtractionStorage

    db = Database(db_path)
    await db.initialize()

    # Get parsed document
    async with db.connection() as conn:
        cursor = await conn.execute(
            "SELECT filename, raw_text, sections_count, page_count FROM documents WHERE doc_id = ?",
            (doc_id,)
        )
        row = await cursor.fetchone()

        if not row:
            raise ValueError(f"Document {doc_id} not found")

        filename = row["filename"]
        raw_text = row["raw_text"]
        page_count = row["page_count"] or 1

        # Retrieve sections (page_start may be NULL for pre-migration data)
        cursor = await conn.execute(
            """
            SELECT title, content, page_start, page_end
            FROM sections
            WHERE doc_id = ?
            ORDER BY section_index
            """,
            (doc_id,)
        )
        section_rows = await cursor.fetchall()
        sections = [
            Section(
                title=row["title"],
                content=row["content"],
                page_start=row["page_start"],
                page_end=row["page_end"],
            )
            for row in section_rows
        ]

        # Older completed documents may have raw_text cleared. Reconstruct a
        # usable overview source from the canonical sections when needed.
        if not raw_text:
            raw_text = "\n\n".join(
                "\n".join(part for part in (section.title, section.content) if part).strip()
                for section in sections
                if (section.title or section.content)
            )

    logger.info(
        f"Starting extraction for {filename}... "
        f"analysis_context={analysis_context or 'none (base extraction)'}"
    )

    # Update status
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE documents SET status = ? WHERE doc_id = ?",
            ("extracting", doc_id)
        )
        await conn.commit()

    # Create extraction objects
    from .embeddings import EmbeddingService

    extractor = DocumentExtractor(extraction_model_override=extraction_model, org_id=org_id)

    # Initialize embedding service for semantic search
    try:
        embedding_service = EmbeddingService()
        logger.info("Embedding service initialized for extraction")
    except ImportError:
        logger.warning("sentence-transformers not available. Embeddings disabled.")
        embedding_service = None

    storage = ExtractionStorage(db, embedding_service=embedding_service)

    # Reconstruct ParseResult with actual sections
    parse_result = ParseResult(
        filename=filename,
        sections=sections,
        raw_text=raw_text,
        page_count=page_count,
        metadata={}
    )

    try:
        return await _run_extraction_pipeline(
            doc_id=doc_id, db=db, extractor=extractor, storage=storage,
            parse_result=parse_result, sections=sections, filename=filename,
            analysis_context=analysis_context,
        )
    except Exception:
        # Set document status to "failed" so it doesn't stay stuck in "extracting"
        async with db.connection() as conn:
            await conn.execute(
                "UPDATE documents SET status = ? WHERE doc_id = ?",
                ("failed", doc_id)
            )
            await conn.commit()
        raise


async def _run_extraction_pipeline(
    *,
    doc_id: str,
    db: Database,
    extractor: "DocumentExtractor",
    storage: "ExtractionStorage",
    parse_result: "ParseResult",
    sections: list,
    filename: str,
    analysis_context: Optional[str],
) -> Dict[str, Any]:
    """Core extraction pipeline (Pass 1-3). Separated to allow error handling in caller."""
    # Pass 1: Extract overview
    logger.info("Pass 1: Extracting document overview...")
    overview = await extractor.extract_overview(parse_result)
    await storage.store_entities(doc_id, overview.entities)

    # Pass 2: Extract from each section (with optional domain-specific supplements)
    logger.info(f"Pass 2: Extracting truths from {len(sections)} sections...")
    all_truths = []
    all_entities = []
    all_relationships = []

    failed_sections: list[str] = []
    for idx, section in enumerate(sections):
        logger.info(f"  Extracting section {idx + 1}/{len(sections)}: {section.title}...")
        try:
            section_extraction = await extractor.extract_section(
                section_title=section.title,
                section_content=section.content,
                doc_context=overview,
                filename=filename,
                page=section.page_start,
                analysis_context=analysis_context,
            )
        except Exception as exc:
            logger.warning(
                "Section %d/%d '%s' extraction failed, skipping: %s",
                idx + 1, len(sections), section.title, exc,
            )
            failed_sections.append(section.title)
            continue

        all_truths.extend(section_extraction.truths)
        all_entities.extend(section_extraction.entities)
        all_relationships.extend(section_extraction.relationships)

        # Store incrementally so poll requests see progress
        if section_extraction.truths:
            await storage.store_truths(doc_id, section_extraction.truths)
        if section_extraction.entities:
            await storage.store_entities(doc_id, section_extraction.entities)
        if section_extraction.relationships:
            await storage.store_relationships(doc_id, section_extraction.relationships)

    if failed_sections:
        logger.warning(
            "Extraction completed with %d/%d sections failed: %s",
            len(failed_sections), len(sections), failed_sections,
        )

    # If ALL sections failed, abort — the document has no useful data
    if sections and len(failed_sections) == len(sections):
        raise ValueError(
            f"All {len(sections)} sections failed extraction. "
            f"First failure: {failed_sections[0]}"
        )

    # Pass 3: Cross-section synthesis (only when analysis_context is provided)
    synthesis_output = None
    if analysis_context:
        logger.info(
            f"Pass 3: Running synthesis for analysis_context='{analysis_context}'..."
        )
        try:
            synthesis = await extractor.synthesize(
                filename=filename,
                doc_context=overview,
                all_truths=all_truths,
                all_entities=all_entities,
                all_relationships=all_relationships,
                section_count=len(sections),
                analysis_context=analysis_context,
            )
            synthesis_output = {
                "analysis_context": synthesis.analysis_context,
                "component_registry": [
                    {
                        "name": c.name,
                        "component_type": c.component_type,
                        "evidence_refs": c.evidence_refs,
                        "properties": c.properties,
                    }
                    for c in synthesis.component_registry
                ],
                "trust_boundaries": [
                    {
                        "source_domain": tb.source_domain,
                        "destination_domain": tb.destination_domain,
                        "data_transferred": tb.data_transferred,
                        "protocol_mechanism": tb.protocol_mechanism,
                        "components_involved": tb.components_involved,
                        "evidence": tb.evidence,
                    }
                    for tb in synthesis.trust_boundaries
                ],
                "implicit_negatives": [
                    {
                        "missing_topic": neg.missing_topic,
                        "relevance_context": neg.relevance_context,
                        "related_topics_present": neg.related_topics_present,
                    }
                    for neg in synthesis.implicit_negatives
                ],
                "ambiguities": [
                    {
                        "vague_term": amb.vague_term,
                        "source_statement": amb.source_statement,
                        "section": amb.section,
                        "clarification_needed": amb.clarification_needed,
                    }
                    for amb in synthesis.ambiguities
                ],
            }

            # Compliance mapping fields (populated when analysis_context="compliance_mapping")
            if synthesis.obligation_registry:
                synthesis_output["obligation_registry"] = [
                    {
                        "obligation_id": obl.obligation_id,
                        "article_reference": obl.article_reference,
                        "obligation_text": obl.obligation_text,
                        "responsible_party": obl.responsible_party,
                        "action_required": obl.action_required,
                        "obligation_type": obl.obligation_type,
                        "deadline": obl.deadline,
                        "conditions": obl.conditions,
                        "exemptions": obl.exemptions,
                        "evidence": obl.evidence,
                    }
                    for obl in synthesis.obligation_registry
                ]

            if synthesis.deadline_inventory:
                synthesis_output["deadline_inventory"] = [
                    {
                        "deadline_id": dl.deadline_id,
                        "requirement": dl.requirement,
                        "article_reference": dl.article_reference,
                        "duration": dl.duration,
                        "trigger_event": dl.trigger_event,
                        "deadline_type": dl.deadline_type,
                        "responsible_party": dl.responsible_party,
                        "evidence": dl.evidence,
                    }
                    for dl in synthesis.deadline_inventory
                ]

            if synthesis.penalty_structures:
                synthesis_output["penalty_structures"] = [
                    {
                        "penalty_id": pen.penalty_id,
                        "article_reference": pen.article_reference,
                        "violation_category": pen.violation_category,
                        "enforcement_body": pen.enforcement_body,
                        "max_fine_absolute": pen.max_fine_absolute,
                        "max_fine_revenue_based": pen.max_fine_revenue_based,
                        "calculation_method": pen.calculation_method,
                        "criminal_sanctions": pen.criminal_sanctions,
                        "administrative_measures": pen.administrative_measures,
                        "aggravating_factors": pen.aggravating_factors,
                        "mitigating_factors": pen.mitigating_factors,
                        "private_right_of_action": pen.private_right_of_action,
                        "evidence": pen.evidence,
                    }
                    for pen in synthesis.penalty_structures
                ]

            if synthesis.cross_regulation_references:
                synthesis_output["cross_regulation_references"] = [
                    {
                        "reference_id": xref.reference_id,
                        "source_article": xref.source_article,
                        "referenced_instrument": xref.referenced_instrument,
                        "reference_type": xref.reference_type,
                        "relationship_description": xref.relationship_description,
                        "evidence": xref.evidence,
                    }
                    for xref in synthesis.cross_regulation_references
                ]

            if synthesis.scope_definitions:
                sd = synthesis.scope_definitions
                synthesis_output["scope_definitions"] = {
                    "entity_types_included": [
                        {
                            "entity_type": et.entity_type,
                            "description": et.description,
                            "article_reference": et.article_reference,
                            "evidence": et.evidence,
                        }
                        for et in sd.entity_types_included
                    ],
                    "entity_types_excluded": [
                        {
                            "entity_type": et.entity_type,
                            "description": et.description,
                            "article_reference": et.article_reference,
                            "evidence": et.evidence,
                        }
                        for et in sd.entity_types_excluded
                    ],
                    "data_types_in_scope": sd.data_types_in_scope,
                    "geographic_scope": sd.geographic_scope,
                    "sectoral_scope": sd.sectoral_scope,
                    "material_scope": sd.material_scope,
                    "applicability_thresholds": [
                        {
                            "threshold_type": at.threshold_type,
                            "value": at.value,
                            "article_reference": at.article_reference,
                        }
                        for at in sd.applicability_thresholds
                    ],
                }
            logger.info(
                f"Pass 3 complete: {len(synthesis.component_registry)} components, "
                f"{len(synthesis.trust_boundaries)} trust boundaries, "
                f"{len(synthesis.implicit_negatives)} implicit negatives, "
                f"{len(synthesis.ambiguities)} ambiguities"
            )
        except Exception as e:
            # Synthesis failure is non-fatal — we still have Pass 1+2 data
            logger.error(
                f"Pass 3 synthesis failed (non-fatal): {type(e).__name__}: {e}",
                exc_info=True,
            )
            synthesis_output = {
                "error": f"Synthesis failed: {type(e).__name__}: {e}",
                "analysis_context": analysis_context,
            }

    # Keep raw_text so completed documents can be re-extracted faithfully.
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE documents SET status = ? WHERE doc_id = ?",
            ("completed", doc_id)
        )
        await conn.commit()

    logger.info(f"Extraction complete for {filename}: {len(all_truths)} truths, {len(all_entities)} entities, {len(all_relationships)} relationships")

    # Combine overview entities with section entities
    combined_entities = list(overview.entities) + all_entities

    result = {
        "doc_id": doc_id,
        "status": "completed",
        "truths_extracted": len(all_truths),
        "entities_found": len(combined_entities),
        "relationships_found": len(all_relationships),
        # Include full extracted data for downstream agent consumption
        "overview": {
            "purpose": overview.purpose,
            "topics": overview.topics,
            "document_type": overview.document_type,
        },
        "truths": [
            {
                "statement": t.statement,
                "section": t.section,
                "page": t.page,
                "paragraph": t.paragraph,
                "statement_type": t.statement_type.value,
                "confidence": t.confidence,
                "entities": t.entities,
                "document_name": t.document_name,
            }
            for t in all_truths
        ],
        "entities": [
            {
                "name": e.name,
                "entity_type": e.entity_type,
                "context": e.context,
            }
            for e in combined_entities
        ],
        "relationships": [
            {
                "entity_a": r.entity_a,
                "entity_b": r.entity_b,
                "relationship_type": r.relationship_type,
                "evidence": r.evidence,
                "confidence": r.confidence,
                "source_component": r.source_component,
                "destination_component": r.destination_component,
                "data_transferred": r.data_transferred,
                "protocol_mechanism": r.protocol_mechanism,
            }
            for r in all_relationships
        ],
    }

    # Include synthesis output when analysis_context was provided
    if synthesis_output is not None:
        result["synthesis"] = synthesis_output

    return result


async def list_documents_tool(db_path: Path, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """
    List documents in the database with extraction status and counts.

    Returns a catalog of documents for agent discovery — lets agents
    know what's been parsed/extracted without fetching full data.
    """
    db = Database(db_path)
    await db.initialize()

    async with db.connection() as conn:
        # Get total count
        count_cursor = await conn.execute("SELECT COUNT(*) as cnt FROM documents")
        total = (await count_cursor.fetchone())["cnt"]

        cursor = await conn.execute("""
            SELECT d.doc_id, d.filename, d.status, d.upload_date, d.sections_count,
                   COUNT(DISTINCT t.truth_id) as truths_count,
                   COUNT(DISTINCT e.entity_id) as entities_count,
                   COUNT(DISTINCT r.relationship_id) as relationships_count
            FROM documents d
            LEFT JOIN truths t ON d.doc_id = t.doc_id
            LEFT JOIN entities e ON d.doc_id = e.doc_id
            LEFT JOIN relationships r ON d.doc_id = r.source_doc_id
            GROUP BY d.doc_id
            ORDER BY d.upload_date DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        rows = await cursor.fetchall()
        documents = [dict(row) for row in rows]

    return {"documents": documents, "count": len(documents), "total": total}


async def get_document_tool(
    doc_id: str,
    db_path: Path,
    include_extracted_data: bool = False,
    include_sections: bool = False,
) -> Dict[str, Any]:
    """
    Get full document details including all extracted data.

    Returns metadata + counts for a single document.
    Optional sections and extracted data are returned when requested.
    """
    db = Database(db_path)
    await db.initialize()

    async with db.connection() as conn:
        # Fetch document metadata
        cursor = await conn.execute(
            "SELECT doc_id, filename, status, upload_date, sections_count, raw_text, metadata FROM documents WHERE doc_id = ?",
            (doc_id,)
        )
        doc_row = await cursor.fetchone()

        if not doc_row:
            raise ValueError(f"Document {doc_id} not found")

        result = dict(doc_row)

        # Parse metadata JSON
        import json
        if result.get("metadata"):
            try:
                result["metadata"] = json.loads(result["metadata"])
            except (json.JSONDecodeError, TypeError):
                result["metadata"] = {}

        # Always fetch counts (lightweight)
        count_cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM truths WHERE doc_id = ?", (doc_id,)
        )
        result["truths_count"] = (await count_cursor.fetchone())["cnt"]

        count_cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM entities WHERE doc_id = ?", (doc_id,)
        )
        result["entities_count"] = (await count_cursor.fetchone())["cnt"]

        count_cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM relationships WHERE source_doc_id = ?", (doc_id,)
        )
        result["relationships_count"] = (await count_cursor.fetchone())["cnt"]

        if include_sections or include_extracted_data:
            cursor = await conn.execute("""
                SELECT title, content, section_index, page_start, page_end
                FROM sections
                WHERE doc_id = ?
                ORDER BY section_index
            """, (doc_id,))
            result["sections"] = [
                {
                    "section_ref": f"section-{row['section_index'] + 1}",
                    "title": row["title"],
                    "content": row["content"],
                    "section_index": row["section_index"],
                    "page_start": row["page_start"],
                    "page_end": row["page_end"],
                    "parent_ref": None,
                }
                for row in await cursor.fetchall()
            ]

        # Only fetch full extracted data when requested (prevents context window explosion)
        if include_extracted_data:
            # Fetch truths
            cursor = await conn.execute("""
                SELECT
                    t.truth_id, t.statement, t.source_section,
                    t.source_page, t.source_paragraph, t.statement_type,
                    t.confidence, t.source_authority
                FROM truths t
                WHERE t.doc_id = ?
            """, (doc_id,))
            truth_rows = await cursor.fetchall()

            # Batch-fetch all truth-entity mappings (eliminates N+1 queries)
            truth_ids = [row["truth_id"] for row in truth_rows]
            entity_map: dict[str, list[str]] = {tid: [] for tid in truth_ids}
            if truth_ids:
                placeholders = ",".join("?" for _ in truth_ids)
                entity_cursor = await conn.execute(f"""
                    SELECT te.truth_id, e.entity_name
                    FROM truth_entities te
                    JOIN entities e ON te.entity_id = e.entity_id
                    WHERE te.truth_id IN ({placeholders})
                """, truth_ids)
                for erow in await entity_cursor.fetchall():
                    entity_map[erow["truth_id"]].append(erow["entity_name"])

            result["truths"] = [
                {
                    "truth_id": row["truth_id"],
                    "statement": row["statement"],
                    "source_section": row["source_section"],
                    "source_page": row["source_page"],
                    "source_paragraph": row["source_paragraph"],
                    "statement_type": row["statement_type"],
                    "confidence": row["confidence"],
                    "source_authority": row["source_authority"],
                    "related_entities": entity_map.get(row["truth_id"], []),
                }
                for row in truth_rows
            ]

            # Fetch entities
            cursor = await conn.execute("""
                SELECT entity_id, entity_name, entity_type, mention_count
                FROM entities
                WHERE doc_id = ?
            """, (doc_id,))
            result["entities"] = [dict(row) for row in await cursor.fetchall()]

            # Fetch relationships with entity name joins
            cursor = await conn.execute("""
                SELECT
                    r.relationship_id,
                    ea.entity_name as entity_a,
                    r.relationship_type,
                    eb.entity_name as entity_b,
                    r.source_section,
                    r.confidence
                FROM relationships r
                JOIN entities ea ON r.entity_a_id = ea.entity_id
                JOIN entities eb ON r.entity_b_id = eb.entity_id
                WHERE r.source_doc_id = ?
            """, (doc_id,))
            result["relationships"] = [dict(row) for row in await cursor.fetchall()]

    return result


async def delete_document_tool(doc_id: str, db_path: Path) -> Dict[str, Any]:
    """
    Delete a document and all associated extracted data.

    Cascade deletes: truths, truth_entities, entities, relationships, sections,
    and the document record itself. Use for data lifecycle management.
    """
    db = Database(db_path)
    await db.initialize()

    async with db.connection() as conn:
        # Verify document exists
        cursor = await conn.execute(
            "SELECT doc_id, filename FROM documents WHERE doc_id = ?",
            (doc_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Document {doc_id} not found")

        filename = row["filename"]

        # Delete in dependency order (child tables first)
        # truth_entities references both truths and entities
        await conn.execute("""
            DELETE FROM truth_entities WHERE truth_id IN (
                SELECT truth_id FROM truths WHERE doc_id = ?
            )
        """, (doc_id,))
        await conn.execute("DELETE FROM truths WHERE doc_id = ?", (doc_id,))
        await conn.execute("""
            DELETE FROM relationships WHERE source_doc_id = ?
        """, (doc_id,))
        await conn.execute("""
            DELETE FROM entity_aliases WHERE entity_a_id IN (
                SELECT entity_id FROM entities WHERE doc_id = ?
            ) OR entity_b_id IN (
                SELECT entity_id FROM entities WHERE doc_id = ?
            )
        """, (doc_id, doc_id))
        await conn.execute("DELETE FROM entities WHERE doc_id = ?", (doc_id,))
        await conn.execute("DELETE FROM sections WHERE doc_id = ?", (doc_id,))
        await conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        await conn.commit()

    logger.info(f"Deleted document {doc_id} ({filename}) and all associated data")

    return {
        "deleted": doc_id,
        "filename": filename,
        "status": "deleted",
    }


async def resolve_technology_name_tool(raw_name: str) -> Dict[str, Any]:
    """
    Resolve a raw technology string to its canonical name using the
    technology terminology resource.

    Deterministic normalization that handles:
    - Aliases: "ELK Stack" → "Elasticsearch (Elastic Stack)"
    - Abbreviations: "PG" → "PostgreSQL"
    - Version stripping: "PostgreSQL 15.3" → canonical "PostgreSQL", version "15.3"
    - Typo correction: "Elasticsearh" → "Elasticsearch (Elastic Stack)" (fuzzy, 0.85 threshold)
    - Renames: "Azure AD" → "Microsoft Entra ID"

    Returns null canonical_name when no match is found or when the match is
    ambiguous (multiple possible canonicals for the same alias).
    """
    result = _resolve_tech(raw_name)

    # Determine match method and confidence for downstream agents
    if not result["matched"]:
        return {
            "canonical_name": None,
            "original": result["original"],
            "version": result["version"],
            "category": None,
            "match_method": None,
            "confidence": 0.0,
            "disambiguation_note": result["disambiguation_note"],
        }

    # Determine match method: exact vs fuzzy
    # If the lowered, version-stripped input is in the alias index directly, it's exact
    from . import resources as _res_mod
    _res_mod._load_terminology()

    stripped = _res_mod._VERSION_PATTERN.sub("", raw_name.strip()).strip().lower()
    is_exact = stripped in _res_mod._ALIAS_INDEX and _res_mod._ALIAS_INDEX[stripped] is not None

    return {
        "canonical_name": result["canonical_name"],
        "original": result["original"],
        "version": result["version"],
        "category": result["category"],
        "match_method": "exact" if is_exact else "fuzzy",
        "confidence": 1.0 if is_exact else 0.85,
        "disambiguation_note": result["disambiguation_note"],
    }


async def suggest_terminology_addition_tool(
    raw_string: str,
    resolved_canonical: str | None = None,
    context: str | None = None,
    db_path: Path | None = None,
) -> Dict[str, Any]:
    """
    Queue a terminology addition suggestion for human review.

    Called by the DFD Builder when it performs a semantic merge on technology
    names not already in the terminology table. Suggestions are persisted in
    the database for review — they do NOT modify the terminology file directly.

    Args:
        raw_string: The unresolved technology string from the source document
        resolved_canonical: What the DFD Builder resolved it to (via LLM dedup)
        context: A snippet from the source document providing usage context
        db_path: Path to SQLite database for persistence
    """
    suggestion = _suggest_term(
        canonical_name=resolved_canonical or raw_string,
        aliases=[raw_string],
        category="Unclassified",
        disambiguation_note=None,
        source_engagement=context,
    )

    # Persist to database if db_path is available
    if db_path:
        db = Database(db_path)
        await db.initialize()

        # Ensure the suggestions table exists
        async with db.connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS terminology_suggestions (
                    suggestion_id TEXT PRIMARY KEY,
                    raw_string TEXT NOT NULL,
                    resolved_canonical TEXT,
                    context TEXT,
                    status TEXT NOT NULL DEFAULT 'pending_review',
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewer_action TEXT
                )
            """)
            suggestion_id = str(uuid.uuid4())
            await conn.execute("""
                INSERT OR IGNORE INTO terminology_suggestions
                    (suggestion_id, raw_string, resolved_canonical, context, status, created_at)
                VALUES (?, ?, ?, ?, 'pending_review', ?)
            """, (
                suggestion_id,
                raw_string,
                resolved_canonical,
                context,
                datetime.now().isoformat(),
            ))
            await conn.commit()

        suggestion["suggestion_id"] = suggestion_id
        suggestion["persisted"] = True
        logger.info(f"Terminology suggestion queued: '{raw_string}' → '{resolved_canonical}'")
    else:
        suggestion["persisted"] = False

    return suggestion
