"""HTTP/SSE server for Document-Logic MCP."""

import asyncio
import base64
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .database import Database
from .export import AssessmentExporter
from .query import QueryEngine
from .tools import (
    MAX_FILE_SIZE,
    _load_document_for_access,
    delete_document_tool,
    extract_document_tool,
    get_document_tool,
    list_documents_tool,
    parse_document_tool,
    resolve_technology_name_tool,
    suggest_terminology_addition_tool,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("DB_PATH", "data/assessment.db"))
MCP_API_KEY = os.getenv("MCP_API_KEY", "").strip()
MCP_AUTH_DISABLED = os.getenv("MCP_AUTH_DISABLED", "").strip().lower() in {"1", "true", "yes"}

# Global database path set during app lifespan.
db_path: Path | None = None


@dataclass(slots=True)
class AccessContext:
    org_id: str
    user_id: str | None = None
    allow_org_write: bool = False


class ParseDocumentRequest(BaseModel):
    file_path: str = Field(..., description="Absolute path to document file")
    scope: Literal["conversation", "organization"] = Field(
        "conversation",
        description="Storage scope for the document",
    )


class ParseContentRequest(BaseModel):
    filename: str = Field(..., description="Original filename (with extension)")
    content: str = Field(..., description="Base64-encoded file content")
    scope: Literal["conversation", "organization"] = Field(
        "conversation",
        description="Storage scope for the document",
    )


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
        ),
    )


class QueryDocumentsRequest(BaseModel):
    query: str = Field(..., description="Natural language query")
    doc_ids: list[str] | None = Field(None, description="Optional: limit to specific documents")
    limit: int = Field(20, ge=1, le=100, description="Maximum results to return (1-100)")


class EntityAliasesRequest(BaseModel):
    entity_name: str = Field(..., description="Exact entity name to look up")


class ResolveTechnologyNameRequest(BaseModel):
    raw_name: str = Field(
        ...,
        description="Raw technology string from source document (e.g., 'ELK Stack', 'PostgreSQL 15.3', 'Azure AD')",
    )


class SuggestTerminologyAdditionRequest(BaseModel):
    raw_string: str = Field(..., description="The unresolved technology string from the source document")
    resolved_canonical: str | None = Field(
        None,
        description="What the agent resolved it to via semantic dedup",
    )
    context: str | None = Field(None, description="Snippet from the source document providing usage context")


class ExportAssessmentRequest(BaseModel):
    format: Literal["json", "sqlite", "markdown"] = Field(
        "json",
        description="Export format: json, sqlite, or markdown",
    )
    output_path: str = Field(..., description="Absolute path to save the export file")


def _header_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes"}


def require_access_context(
    x_org_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    x_allow_org_write: str | None = Header(default=None),
) -> AccessContext:
    if not MCP_AUTH_DISABLED:
        if not MCP_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MCP_API_KEY is not configured.",
            )
        if x_api_key != MCP_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid MCP API key.",
            )

    if x_org_id is None or not x_org_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Org-Id header is required.",
        )

    user_id = x_user_id.strip() if x_user_id and x_user_id.strip() else None
    return AccessContext(
        org_id=x_org_id.strip(),
        user_id=user_id,
        allow_org_write=_header_truthy(x_allow_org_write),
    )


def _require_parse_identity(scope: str, access: AccessContext) -> None:
    if scope == "conversation" and not access.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-User-Id header is required for conversation-scoped documents.",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    del app

    global db_path
    db_path = DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = Database(db_path)
    await db.initialize()
    logger.info("Database initialized at %s", db_path)

    yield


app = FastAPI(
    title="Document-Logic MCP",
    description="Structured document intelligence extraction with citations",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint (no authentication required)."""
    import aiosqlite

    status_label = "ok"
    details: Dict[str, Any] = {
        "server": "document-logic-mcp",
        "version": "0.1.0",
    }

    if db_path and db_path.exists():
        try:
            async with aiosqlite.connect(str(db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute("SELECT COUNT(*) as cnt FROM documents")
                row = await cursor.fetchone()
                details["documents_count"] = row["cnt"] if row else 0
                details["db_status"] = "connected"
        except Exception as exc:
            status_label = "degraded"
            details["db_status"] = f"error: {type(exc).__name__}"
    else:
        details["db_status"] = "not_initialized"

    details["status"] = status_label
    return details


@app.post("/parse")
async def parse_document(
    request: ParseDocumentRequest,
    access: AccessContext = Depends(require_access_context),
) -> Dict[str, Any]:
    """Parse a document and extract structure."""
    try:
        _require_parse_identity(request.scope, access)
        return await parse_document_tool(
            file_path=request.file_path,
            db_path=db_path,
            org_id=access.org_id,
            scope=request.scope,
            owner_user_id=access.user_id,
            allow_org_write=access.allow_org_write,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Parse failed: %s", exc)
        raise HTTPException(status_code=500, detail="Document parsing failed")


@app.post("/parse-content")
async def parse_content(
    request: ParseContentRequest,
    access: AccessContext = Depends(require_access_context),
) -> Dict[str, Any]:
    """Parse document content and extract structure (no filesystem access needed)."""
    try:
        _require_parse_identity(request.scope, access)
        file_content = base64.b64decode(request.content)
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"File too large: {len(file_content) / (1024 * 1024):.1f} MB "
                    f"(max {MAX_FILE_SIZE / (1024 * 1024):.0f} MB)"
                ),
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(request.filename).suffix) as temp_file:
            temp_file.write(file_content)
            temp_path = temp_file.name

        try:
            return await parse_document_tool(
                file_path=temp_path,
                db_path=db_path,
                org_id=access.org_id,
                scope=request.scope,
                owner_user_id=access.user_id,
                allow_org_write=access.allow_org_write,
                filename_override=request.filename,
            )
        finally:
            Path(temp_path).unlink(missing_ok=True)
    except HTTPException:
        raise
    except PermissionError as exc:
        logger.error("Parse content rejected: %s", exc)
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        logger.error("Parse content rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Parse content failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Parse failed: {type(exc).__name__}: {exc}")


@app.post("/extract")
async def extract_document(
    request: ExtractDocumentRequest,
    access: AccessContext = Depends(require_access_context),
) -> Dict[str, Any]:
    """Extract truths, entities, and relationships from a parsed document."""
    try:
        return await extract_document_tool(
            doc_id=request.doc_id,
            db_path=db_path,
            extraction_model=request.model,
            analysis_context=request.analysis_context,
            org_id=access.org_id,
            user_id=access.user_id,
            allow_org_write=access.allow_org_write,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Extract failed: %s", exc)
        raise HTTPException(status_code=500, detail="Document extraction failed")


@app.post("/extract-async")
async def extract_document_async(
    request: ExtractDocumentRequest,
    access: AccessContext = Depends(require_access_context),
) -> JSONResponse:
    """Start extraction as a background task and return immediately."""
    if not db_path or not db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")

    db = Database(db_path)
    await db.initialize()

    try:
        async with db.connection() as conn:
            row = await _load_document_for_access(
                conn,
                doc_id=request.doc_id,
                org_id=access.org_id,
                user_id=access.user_id,
                allow_org_write=access.allow_org_write,
                require_write=True,
            )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

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

    asyncio.create_task(
        _background_extract(
            doc_id=request.doc_id,
            org_id=access.org_id,
            user_id=access.user_id,
            allow_org_write=access.allow_org_write,
            extraction_model=request.model,
            analysis_context=request.analysis_context,
        )
    )

    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "doc_id": request.doc_id},
    )


async def _background_extract(
    *,
    doc_id: str,
    org_id: str,
    user_id: str | None,
    allow_org_write: bool,
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
            org_id=org_id,
            user_id=user_id,
            allow_org_write=allow_org_write,
        )
        logger.info("Background extraction completed for %s", doc_id)
    except Exception:
        logger.exception("Background extraction failed for %s", doc_id)


@app.get("/documents")
async def list_documents(
    limit: int = 100,
    offset: int = 0,
    access: AccessContext = Depends(require_access_context),
) -> Dict[str, Any]:
    """List documents with extraction status and counts."""
    try:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        return await list_documents_tool(
            db_path=db_path,
            org_id=access.org_id,
            user_id=access.user_id,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.error("List documents failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list documents")


@app.get("/documents/{doc_id}")
async def get_document(
    doc_id: str,
    include_extracted_data: bool = False,
    access: AccessContext = Depends(require_access_context),
) -> Dict[str, Any]:
    """Get document details."""
    try:
        return await get_document_tool(
            doc_id=doc_id,
            db_path=db_path,
            include_extracted_data=include_extracted_data,
            org_id=access.org_id,
            user_id=access.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Get document failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to get document")


@app.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    access: AccessContext = Depends(require_access_context),
) -> Dict[str, Any]:
    """Delete a document and all associated extracted data."""
    try:
        return await delete_document_tool(
            doc_id=doc_id,
            db_path=db_path,
            org_id=access.org_id,
            user_id=access.user_id,
            allow_org_write=access.allow_org_write,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Delete document failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to delete document")


@app.post("/query-documents")
async def query_documents(
    request: QueryDocumentsRequest,
    access: AccessContext = Depends(require_access_context),
) -> Dict[str, Any]:
    """Query extracted truths with natural language."""
    try:
        from .embeddings import EmbeddingService

        db = Database(db_path)
        await db.initialize()

        try:
            embedding_service = EmbeddingService()
        except ImportError:
            embedding_service = None

        query_engine = QueryEngine(db, embedding_service=embedding_service)
        results = await query_engine.query(
            request.query,
            org_id=access.org_id,
            user_id=access.user_id,
            doc_ids=request.doc_ids,
            top_k=request.limit,
        )
        return {"results": results, "count": len(results)}
    except Exception as exc:
        logger.error("Query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Query execution failed")


@app.post("/entity-aliases")
async def get_entity_aliases(
    request: EntityAliasesRequest,
    access: AccessContext = Depends(require_access_context),
) -> Dict[str, Any]:
    """Find potential aliases for a named entity."""
    try:
        from .embeddings import EmbeddingService

        db = Database(db_path)
        await db.initialize()

        try:
            embedding_service = EmbeddingService()
        except ImportError:
            embedding_service = None

        query_engine = QueryEngine(db, embedding_service=embedding_service)
        return await query_engine.get_entity_aliases(
            request.entity_name,
            org_id=access.org_id,
            user_id=access.user_id,
        )
    except Exception as exc:
        logger.error("Entity aliases failed: %s", exc)
        raise HTTPException(status_code=500, detail="Entity alias lookup failed")


@app.post("/resolve-technology-name")
async def resolve_technology_name(
    request: ResolveTechnologyNameRequest,
    access: AccessContext = Depends(require_access_context),
) -> Dict[str, Any]:
    """Resolve a raw technology string to its canonical name."""
    del access

    try:
        return await resolve_technology_name_tool(raw_name=request.raw_name)
    except Exception as exc:
        logger.error("Resolve technology name failed: %s", exc)
        raise HTTPException(status_code=500, detail="Technology name resolution failed")


@app.post("/suggest-terminology-addition")
async def suggest_terminology_addition(
    request: SuggestTerminologyAdditionRequest,
    access: AccessContext = Depends(require_access_context),
) -> Dict[str, Any]:
    """Queue a terminology addition suggestion for human review."""
    try:
        return await suggest_terminology_addition_tool(
            raw_string=request.raw_string,
            resolved_canonical=request.resolved_canonical,
            context=request.context,
            db_path=db_path,
            org_id=access.org_id,
            user_id=access.user_id,
        )
    except Exception as exc:
        logger.error("Suggest terminology addition failed: %s", exc)
        raise HTTPException(status_code=500, detail="Terminology suggestion failed")


@app.post("/export")
async def export_assessment(
    request: ExportAssessmentRequest,
    access: AccessContext = Depends(require_access_context),
) -> Dict[str, Any]:
    """Export accessible extracted data as a deliverable file."""
    try:
        db = Database(db_path)
        await db.initialize()
        exporter = AssessmentExporter(
            db,
            org_id=access.org_id,
            user_id=access.user_id,
        )

        output_path = Path(request.output_path)
        if request.format == "json":
            result_path = await exporter.export_json(output_path)
        elif request.format == "sqlite":
            result_path = await exporter.export_sqlite(output_path)
        else:
            result_path = await exporter.export_markdown(output_path)

        return {"exported_to": str(result_path), "format": request.format}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Export failed: %s", exc)
        raise HTTPException(status_code=500, detail="Export failed")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
