"""MCP tool implementations."""

import logging
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
from .database import Database
from .parsers import PDFParser, DOCXParser, JSONParser
from .extraction import DocumentExtractor

logger = logging.getLogger(__name__)


async def parse_document_tool(file_path: str, db_path: Path) -> Dict[str, Any]:
    """
    Parse a document and store metadata.

    Fast (seconds), deterministic parsing of document structure.
    Returns document ID for use in extract_document.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Select parser based on extension
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        parser = PDFParser()
    elif suffix in [".docx", ".doc"]:
        parser = DOCXParser()
    elif suffix == ".json":
        parser = JSONParser()
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    # Parse document
    logger.info(f"Parsing {file_path.name}...")
    parse_result = parser.parse(file_path)

    # Store in database
    db = Database(db_path)
    await db.initialize()

    doc_id = str(uuid.uuid4())

    async with db.connection() as conn:
        # Store document metadata
        await conn.execute("""
            INSERT INTO documents (doc_id, filename, upload_date, sections_count, status, raw_text)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            doc_id,
            parse_result.filename,
            datetime.now().isoformat(),
            len(parse_result.sections),
            "parsed",
            parse_result.raw_text
        ))

        # Store sections
        for idx, section in enumerate(parse_result.sections):
            section_id = str(uuid.uuid4())
            await conn.execute("""
                INSERT INTO sections (section_id, doc_id, title, content, section_index)
                VALUES (?, ?, ?, ?, ?)
            """, (
                section_id,
                doc_id,
                section.title,
                section.content,
                idx
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
    extraction_model: str | None = None
) -> Dict[str, Any]:
    """
    Extract truths, entities, and relationships from parsed document.

    Slow (minutes), LLM-based hierarchical extraction.
    Blocks until complete - honest about wait time.

    Args:
        doc_id: Document ID from parse operation
        db_path: Path to SQLite database
        extraction_model: Optional model override (e.g., 'ollama/llama3.1')
    """
    from .parsers.base import ParseResult, Section
    from .storage import ExtractionStorage
    from .extraction import SourceAuthority

    db = Database(db_path)

    # Get parsed document
    async with db.connection() as conn:
        cursor = await conn.execute(
            "SELECT filename, raw_text, sections_count FROM documents WHERE doc_id = ?",
            (doc_id,)
        )
        row = await cursor.fetchone()

        if not row:
            raise ValueError(f"Document {doc_id} not found")

        filename = row["filename"]
        raw_text = row["raw_text"]
        sections_count = row["sections_count"]

        # Retrieve sections
        cursor = await conn.execute(
            "SELECT title, content FROM sections WHERE doc_id = ? ORDER BY section_index",
            (doc_id,)
        )
        section_rows = await cursor.fetchall()
        sections = [Section(title=row["title"], content=row["content"]) for row in section_rows]

    logger.info(f"Starting extraction for {filename}...")

    # Update status
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE documents SET status = ? WHERE doc_id = ?",
            ("extracting", doc_id)
        )
        await conn.commit()

    # Create extraction objects
    from .embeddings import EmbeddingService

    extractor = DocumentExtractor(extraction_model_override=extraction_model)

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
        page_count=1,
        metadata={}
    )

    # Pass 1: Extract overview
    logger.info("Pass 1: Extracting document overview...")
    overview = await extractor.extract_overview(parse_result)
    await storage.store_entities(doc_id, overview.entities)

    # Pass 2: Extract from each section
    logger.info(f"Pass 2: Extracting truths from {len(sections)} sections...")
    all_truths = []
    all_entities = []
    all_relationships = []

    for idx, section in enumerate(sections):
        logger.info(f"  Extracting section {idx + 1}/{len(sections)}: {section.title}...")
        section_extraction = await extractor.extract_section(
            section_title=section.title,
            section_content=section.content,
            doc_context=overview,
            filename=filename,
            page=None
        )

        all_truths.extend(section_extraction.truths)
        all_entities.extend(section_extraction.entities)
        all_relationships.extend(section_extraction.relationships)

    # Store all extracted data
    await storage.store_truths(doc_id, all_truths)
    await storage.store_entities(doc_id, all_entities)
    await storage.store_relationships(doc_id, all_relationships)

    # Update status
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE documents SET status = ? WHERE doc_id = ?",
            ("completed", doc_id)
        )
        await conn.commit()

    logger.info(f"Extraction complete for {filename}: {len(all_truths)} truths, {len(all_entities)} entities, {len(all_relationships)} relationships")

    return {
        "doc_id": doc_id,
        "status": "completed",
        "truths_extracted": len(all_truths),
        "entities_found": len(overview.entities) + len(all_entities),
        "relationships_found": len(all_relationships)
    }
