"""HTTP/SSE Server for Document-Logic MCP.

Provides HTTP endpoints for document processing tools to integrate with Ansvar platform.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .tools import parse_document_tool, extract_document_tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Document-Logic MCP",
    description="Structured document intelligence extraction with citations",
    version="0.1.0"
)

# Global database path
db_path: Path = None


# Request models
class ParseDocumentRequest(BaseModel):
    file_path: str = Field(..., description="Absolute path to document file")


class ParseContentRequest(BaseModel):
    filename: str = Field(..., description="Original filename (with extension)")
    content: str = Field(..., description="Base64-encoded file content")


class ExtractDocumentRequest(BaseModel):
    doc_id: str = Field(..., description="Document ID from parse_document")


class QueryDocumentsRequest(BaseModel):
    query: str = Field(..., description="Natural language query")
    doc_ids: list[str] | None = Field(None, description="Optional: limit to specific documents")


class ExportAssessmentRequest(BaseModel):
    format: str = Field("json", description="Export format: json, sqlite, or markdown")
    output_path: str | None = Field(None, description="Optional output path")


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "server": "document-logic-mcp"}


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
    except Exception as e:
        logger.error(f"Parse failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Parse content endpoint (accepts base64-encoded content instead of file path)
@app.post("/parse-content")
async def parse_content(request: ParseContentRequest) -> Dict[str, Any]:
    """Parse document content and extract structure (no filesystem access needed)."""
    import base64
    import tempfile

    try:
        # Decode base64 content
        file_content = base64.b64decode(request.content)

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

    except Exception as e:
        logger.error(f"Parse content failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Extract document endpoint
@app.post("/extract")
async def extract_document(request: ExtractDocumentRequest) -> Dict[str, Any]:
    """Extract truths, entities, and relationships from parsed document."""
    try:
        result = await extract_document_tool(
            doc_id=request.doc_id,
            db_path=db_path
        )
        return result
    except Exception as e:
        logger.error(f"Extract failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("startup")
async def startup():
    """Initialize database path on startup."""
    global db_path
    db_path = Path(os.getenv("DB_PATH", "data/assessment.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Database path: {db_path}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
