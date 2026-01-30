"""MCP tool implementations."""

import logging
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
from .database import Database
from .parsers import PDFParser, DOCXParser
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


async def extract_document_tool(doc_id: str, db_path: Path) -> Dict[str, Any]:
    """
    Extract truths, entities, and relationships from parsed document.

    Slow (minutes), LLM-based hierarchical extraction.
    Blocks until complete - honest about wait time.
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

    logger.info(f"Starting extraction for {filename}...")

    # Update status
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE documents SET status = ? WHERE doc_id = ?",
            ("extracting", doc_id)
        )
        await conn.commit()

    # Create extraction objects
    extractor = DocumentExtractor()
    storage = ExtractionStorage(db)

    # Reconstruct ParseResult (simplified - in real impl, store sections in DB)
    parse_result = ParseResult(
        filename=filename,
        sections=[Section(title="Document", content=raw_text)],
        raw_text=raw_text,
        page_count=1,
        metadata={}
    )

    # Pass 1: Extract overview
    logger.info("Pass 1: Extracting document overview...")
    overview = await extractor.extract_overview(parse_result)
    await storage.store_entities(doc_id, overview.entities)

    # Pass 2: Extract sections (simplified - extract from full text for now)
    logger.info("Pass 2: Extracting truths and relationships...")
    section_extraction = await extractor.extract_section(
        section_title="Document",
        section_content=raw_text,
        doc_context=overview,
        filename=filename,
        page=1
    )

    await storage.store_truths(doc_id, section_extraction.truths)
    await storage.store_relationships(doc_id, section_extraction.relationships)

    # Update status
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE documents SET status = ? WHERE doc_id = ?",
            ("completed", doc_id)
        )
        await conn.commit()

    logger.info(f"Extraction complete for {filename}")

    return {
        "doc_id": doc_id,
        "status": "completed",
        "truths_extracted": len(section_extraction.truths),
        "entities_found": len(overview.entities) + len(section_extraction.entities),
        "relationships_found": len(section_extraction.relationships)
    }
