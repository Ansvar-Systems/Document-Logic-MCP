"""HTTP/SSE Server for Document-Logic MCP.

Provides HTTP endpoints for document processing tools to integrate with Ansvar platform.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Security, Depends, APIRouter
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from .tools import (
    parse_document_tool, extract_document_tool, list_documents_tool,
    get_document_tool, delete_document_tool,
    resolve_technology_name_tool, suggest_terminology_addition_tool,
)
from .database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Authentication ---
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(_api_key_header)):
    """Verify API key if MCP_API_KEY is configured. Skip auth if unset (dev mode)."""
    required_key = os.getenv("MCP_API_KEY")
    if not required_key:
        return  # No key configured — allow (dev mode)
    if api_key != required_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key

# Global database path
db_path: Optional[Path] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    global db_path
    db_path = Path(os.getenv("DB_PATH", "data/assessment.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = Database(db_path)
    await db.initialize()
    logger.info(f"Database initialized at {db_path}")

    yield


# Initialize FastAPI app — all endpoints require API key when MCP_API_KEY is set
app = FastAPI(
    title="Document-Logic MCP",
    description="Structured document intelligence extraction with citations",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_api_key)],
)


# --- Unauthenticated health check (override removes app-level auth dependency) ---
_health_router = APIRouter(dependencies=[])


@_health_router.get("/health")
async def health_check():
    """Health check endpoint (no authentication required).

    Returns structured status with DB connectivity, document counts,
    and version info for orchestrator consumption.
    """
    import aiosqlite

    status = "ok"
    details: Dict[str, Any] = {
        "server": "document-logic-mcp",
        "version": "0.1.0",
    }

    # Check DB connectivity and report stats
    if db_path and db_path.exists():
        try:
            async with aiosqlite.connect(str(db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT COUNT(*) as cnt FROM documents"
                )
                row = await cursor.fetchone()
                details["documents_count"] = row["cnt"] if row else 0
                details["db_status"] = "connected"
        except Exception as e:
            status = "degraded"
            details["db_status"] = f"error: {type(e).__name__}"
    else:
        details["db_status"] = "not_initialized"

    details["status"] = status
    return details


app.include_router(_health_router)


# Request models
class ParseDocumentRequest(BaseModel):
    file_path: str = Field(..., description="Absolute path to document file")


class ParseContentRequest(BaseModel):
    filename: str = Field(..., description="Original filename (with extension)")
    content: str = Field(..., description="Base64-encoded file content")


class ParseFileRequest(BaseModel):
    object_key: str = Field(..., description="File-service object key (e.g. '{file_id}/{filename}')")
    filename: str = Field(..., description="Original filename for metadata")


class ExtractDocumentRequest(BaseModel):
    doc_id: str = Field(..., description="Document ID from parse_document")
    model: str | None = Field(None, description="Optional LLM model override (e.g., 'ollama/llama3.1')")
    analysis_context: str | None = Field(
        None,
        description=(
            "Optional domain context for enhanced extraction. "
            "Activates domain-specific prompt supplements (Pass 2) and "
            "cross-section synthesis (Pass 3: component registry, trust boundaries, "
            "implicit negatives, ambiguity flags). "
            "Available: 'stride_threat_modeling', 'tprm_vendor_assessment', 'compliance_mapping'"
        )
    )


class QueryDocumentsRequest(BaseModel):
    query: str = Field(..., description="Natural language query")
    doc_ids: list[str] | None = Field(None, description="Optional: limit to specific documents")
    limit: int = Field(20, ge=1, le=100, description="Maximum results to return (1-100)")


class EntityAliasesRequest(BaseModel):
    entity_name: str = Field(..., description="Exact entity name to look up")


class ResolveTechnologyNameRequest(BaseModel):
    raw_name: str = Field(..., description="Raw technology string from source document (e.g., 'ELK Stack', 'PostgreSQL 15.3', 'Azure AD')")


class SuggestTerminologyAdditionRequest(BaseModel):
    raw_string: str = Field(..., description="The unresolved technology string from the source document")
    resolved_canonical: str | None = Field(None, description="What the agent resolved it to via semantic dedup")
    context: str | None = Field(None, description="Snippet from the source document providing usage context")


class ExportAssessmentRequest(BaseModel):
    format: str = Field("json", description="Export format: json, sqlite, or markdown")
    output_path: str = Field(..., description="Absolute path to save the export file")


# Parse document endpoint
@app.post("/parse")
async def parse_document(request: ParseDocumentRequest) -> Dict[str, Any]:
    """Parse a document and extract structure."""
    try:
        result = await parse_document_tool(
            file_path=request.file_path,
            db_path=db_path
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Parse failed: {e}")
        raise HTTPException(status_code=500, detail="Document parsing failed")


# Parse content endpoint (accepts base64-encoded content instead of file path)
@app.post("/parse-content")
async def parse_content(request: ParseContentRequest) -> Dict[str, Any]:
    """Parse document content and extract structure (no filesystem access needed)."""
    import base64
    import tempfile

    try:
        # Decode base64 content
        file_content = base64.b64decode(request.content)

        # File size check
        from .tools import MAX_FILE_SIZE
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {len(file_content) / (1024*1024):.1f} MB "
                       f"(max {MAX_FILE_SIZE / (1024*1024):.0f} MB)",
            )

        # Write to temporary file for parsing
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(request.filename).suffix) as temp_file:
            temp_file.write(file_content)
            temp_path = temp_file.name

        try:
            # Parse using temporary file path
            result = await parse_document_tool(
                file_path=temp_path,
                db_path=db_path
            )
            # Override filename with original name
            result["filename"] = request.filename
            return result
        finally:
            # Clean up temporary file
            Path(temp_path).unlink(missing_ok=True)

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Parse content rejected: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Parse content failed: {e}")
        raise HTTPException(status_code=500, detail=f"Parse failed: {type(e).__name__}: {e}")


SHARED_FILES_PATH = Path(os.getenv("SHARED_FILES_PATH", "/data/uploads"))


# Parse file endpoint (resolves object_key via shared filesystem)
@app.post("/parse-file")
async def parse_file(request: ParseFileRequest) -> Dict[str, Any]:
    """Parse a document from the shared filesystem by object_key."""
    resolved = (SHARED_FILES_PATH / request.object_key).resolve()
    if not resolved.is_relative_to(SHARED_FILES_PATH.resolve()):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {request.object_key}")

    try:
        result = await parse_document_tool(
            file_path=str(resolved),
            db_path=db_path,
        )
        result["filename"] = request.filename
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Parse-file failed: {e}")
        raise HTTPException(status_code=500, detail="Document parsing failed")


# Extract document endpoint
@app.post("/extract")
async def extract_document(request: ExtractDocumentRequest) -> Dict[str, Any]:
    """Extract truths, entities, and relationships from parsed document.

    When analysis_context is provided, also runs a synthesis pass (Pass 3)
    that produces component registry, trust boundaries, implicit negatives,
    and ambiguity flags. The synthesis output is returned under the "synthesis" key.
    """
    try:
        result = await extract_document_tool(
            doc_id=request.doc_id,
            db_path=db_path,
            extraction_model=request.model,
            analysis_context=request.analysis_context,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Extract failed: {e}")
        raise HTTPException(status_code=500, detail="Document extraction failed")


# Async extract endpoint — fire-and-forget, poll via GET /documents/{doc_id}
@app.post("/extract-async")
async def extract_document_async(request: ExtractDocumentRequest) -> JSONResponse:
    """Start extraction as a background task and return immediately.

    Returns HTTP 202 with {"status": "accepted", "doc_id": "..."}.
    Poll GET /documents/{doc_id} to track progress:
      - status "extracting" → still running
      - status "completed"  → done (truths_count, entities_count populated)
      - status "failed"     → extraction error
    """
    import aiosqlite

    # Validate document exists and is in a valid state for extraction
    if not db_path or not db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")

    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT status FROM documents WHERE doc_id = ?",
            (request.doc_id,),
        )
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Document {request.doc_id} not found")

    doc_status = row["status"]
    if doc_status == "extracting":
        raise HTTPException(status_code=409, detail="Extraction already in progress")
    if doc_status == "completed":
        raise HTTPException(status_code=409, detail="Document already extracted")
    if doc_status != "parsed":
        raise HTTPException(
            status_code=400,
            detail=f"Document status is '{doc_status}', expected 'parsed'",
        )

    # Launch extraction as a background asyncio task
    asyncio.create_task(
        _background_extract(
            doc_id=request.doc_id,
            extraction_model=request.model,
            analysis_context=request.analysis_context,
        )
    )

    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "doc_id": request.doc_id},
    )


async def _background_extract(
    doc_id: str,
    extraction_model: str | None,
    analysis_context: str | None,
) -> None:
    """Run extraction in the background. Errors are captured in document status."""
    try:
        await extract_document_tool(
            doc_id=doc_id,
            db_path=db_path,
            extraction_model=extraction_model,
            analysis_context=analysis_context,
        )
        logger.info("Background extraction completed for %s", doc_id)
    except Exception:
        # extract_document_tool already sets status to "failed" on error
        logger.exception("Background extraction failed for %s", doc_id)


# List documents endpoint
@app.get("/documents")
async def list_documents(limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List documents with extraction status and counts. Supports pagination via ?limit=&offset=."""
    try:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        result = await list_documents_tool(db_path=db_path, limit=limit, offset=offset)
        return result
    except Exception as e:
        logger.error(f"List documents failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to list documents")


# Get document endpoint
@app.get("/documents/{doc_id}")
async def get_document(
    doc_id: str,
    include_extracted_data: bool = False,
    include_sections: bool = False,
) -> Dict[str, Any]:
    """Get document details. Pass include_sections and/or include_extracted_data for full content."""
    try:
        result = await get_document_tool(
            doc_id=doc_id,
            db_path=db_path,
            include_extracted_data=include_extracted_data,
            include_sections=include_sections,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Get document failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get document")


# Delete document endpoint
@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: str) -> Dict[str, Any]:
    """Delete a document and all associated extracted data."""
    try:
        result = await delete_document_tool(doc_id=doc_id, db_path=db_path)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Delete document failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete document")


# Query documents endpoint
@app.post("/query-documents")
async def query_documents(request: QueryDocumentsRequest) -> Dict[str, Any]:
    """Query extracted truths with natural language. Returns verified facts with citations."""
    try:
        from .query import QueryEngine
        from .embeddings import EmbeddingService

        db = Database(db_path)
        await db.initialize()

        try:
            embedding_service = EmbeddingService()
        except ImportError:
            embedding_service = None

        query_engine = QueryEngine(db, embedding_service=embedding_service)
        results = await query_engine.query(request.query, doc_ids=request.doc_ids, top_k=request.limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail="Query execution failed")


# Entity aliases endpoint
@app.post("/entity-aliases")
async def get_entity_aliases(request: EntityAliasesRequest) -> Dict[str, Any]:
    """Find potential aliases for a named entity."""
    try:
        from .query import QueryEngine
        from .embeddings import EmbeddingService

        db = Database(db_path)
        await db.initialize()

        try:
            embedding_service = EmbeddingService()
        except ImportError:
            embedding_service = None

        query_engine = QueryEngine(db, embedding_service=embedding_service)
        result = await query_engine.get_entity_aliases(request.entity_name)
        return result
    except Exception as e:
        logger.error(f"Entity aliases failed: {e}")
        raise HTTPException(status_code=500, detail="Entity alias lookup failed")


# Resolve technology name endpoint
@app.post("/resolve-technology-name")
async def resolve_technology_name(request: ResolveTechnologyNameRequest) -> Dict[str, Any]:
    """Resolve a raw technology string to its canonical name.

    Deterministic normalization using the technology terminology resource.
    Returns canonical_name, version, match_method (exact/fuzzy), and confidence.
    Returns null canonical_name when no match or ambiguous.
    """
    try:
        result = await resolve_technology_name_tool(raw_name=request.raw_name)
        return result
    except Exception as e:
        logger.error(f"Resolve technology name failed: {e}")
        raise HTTPException(status_code=500, detail="Technology name resolution failed")


# Suggest terminology addition endpoint
@app.post("/suggest-terminology-addition")
async def suggest_terminology_addition(request: SuggestTerminologyAdditionRequest) -> Dict[str, Any]:
    """Queue a terminology addition suggestion for human review.

    Called when an agent merges technology names not in the terminology table.
    Persists the suggestion for review — does NOT auto-add to the table.
    """
    try:
        result = await suggest_terminology_addition_tool(
            raw_string=request.raw_string,
            resolved_canonical=request.resolved_canonical,
            context=request.context,
            db_path=db_path,
        )
        return result
    except Exception as e:
        logger.error(f"Suggest terminology addition failed: {e}")
        raise HTTPException(status_code=500, detail="Terminology suggestion failed")


# Export assessment endpoint
@app.post("/export")
async def export_assessment(request: ExportAssessmentRequest) -> Dict[str, Any]:
    """Export all extracted data as a deliverable file."""
    try:
        from .export import AssessmentExporter

        db = Database(db_path)
        await db.initialize()
        exporter = AssessmentExporter(db)

        format_type = request.format
        output_path = Path(request.output_path)

        if format_type == "json":
            result_path = await exporter.export_json(output_path)
        elif format_type == "sqlite":
            result_path = await exporter.export_sqlite(output_path)
        elif format_type == "markdown":
            result_path = await exporter.export_markdown(output_path)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown format: {format_type}")

        return {"exported_to": str(result_path), "format": format_type}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise HTTPException(status_code=500, detail="Export failed")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
