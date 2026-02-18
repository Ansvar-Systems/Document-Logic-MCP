"""Document-Logic MCP Server.

Workflow: parse_document → extract_document → query_documents / export_assessment
"""

import json
import logging
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult
from .tools import (
    parse_document_tool, extract_document_tool, list_documents_tool,
    get_document_tool, delete_document_tool,
    resolve_technology_name_tool, suggest_terminology_addition_tool,
)
from .database import Database

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path("data/assessment.db")


def create_server() -> Server:
    """Create and configure the Document-Logic MCP server."""
    server = Server("document-logic-mcp")

    @server.list_tools()
    async def list_tools():
        """List available tools."""
        return [
            Tool(
                name="parse_document",
                description=(
                    "Parse a document (PDF, DOCX, or JSON) and extract its structure into sections. "
                    "Fast (seconds), deterministic — no LLM involved. This is always the FIRST step; "
                    "call this before extract_document. "
                    "Workflow: parse_document → extract_document → query_documents. "
                    "Returns: {doc_id, filename, sections_count, page_count, status, entities_preview}. "
                    "Use the returned doc_id for extract_document or get_document. "
                    "Do NOT call this on already-parsed documents — use list_documents to check first. "
                    "On error: {error, type} — file_not_found, invalid_input (unsupported format), "
                    "or invalid_input (file too large, max 50 MB configurable via MAX_FILE_SIZE_MB)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": (
                                "Absolute path to the document file. "
                                "Supported formats: .pdf (text-based, not scanned images), "
                                ".docx (not .doc), .json. "
                                "Path must be accessible to the server process."
                            ),
                        }
                    },
                    "required": ["file_path"],
                },
            ),
            Tool(
                name="extract_document",
                description=(
                    "Extract truths, entities, and relationships from a parsed document using LLM. "
                    "SLOW (1-5 min for <10 sections, 10-30+ min for large docs) — blocks until complete. "
                    "Requires parse_document first (status must be 'parsed'). "
                    "Do NOT call on documents with status 'completed' — extraction was already done; "
                    "use get_document to retrieve results instead. "
                    "Pass 1: document overview. Pass 2: per-section truths/entities/relationships. "
                    "Without analysis_context: returns truths/entities/relationships only (no 'synthesis' key). "
                    "With analysis_context: also runs Pass 3 cross-section synthesis, adding a 'synthesis' key "
                    "with component_registry, trust_boundaries, implicit_negatives, ambiguities. "
                    "Returns: {doc_id, status, truths_extracted, entities_found, relationships_found, "
                    "overview, truths[], entities[], relationships[], synthesis? (only when analysis_context set)}. "
                    "After extraction, use query_documents for natural-language search across truths, "
                    "or get_document to retrieve all data for a specific document. "
                    "On error: {error, type} — invalid_input if doc_id not found."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {
                            "type": "string",
                            "description": "Document ID returned by parse_document",
                        },
                        "analysis_context": {
                            "type": "string",
                            "enum": ["stride_threat_modeling", "tprm_vendor_assessment"],
                            "description": (
                                "Optional. Activates domain-specific extraction (Pass 2) and "
                                "cross-section synthesis (Pass 3). Choose ONE based on document type. "
                                "'stride_threat_modeling': for security architecture docs, design docs, "
                                "threat models. Extracts trust boundaries, data flows, implicit negatives, "
                                "ambiguity flags. "
                                "'tprm_vendor_assessment': for vendor questionnaires, SOC2 reports, "
                                "privacy policies, DPAs. Extracts certifications, subprocessors, SLAs, "
                                "data residency, incident response."
                            ),
                        },
                        "extraction_model": {
                            "type": "string",
                            "description": (
                                "Optional LLM model override. Format: 'model_name' or "
                                "'provider/model_name' (e.g., 'ollama/llama3.1'). "
                                "Defaults to EXTRACTION_MODEL env var or 'claude-sonnet-4-20250514'."
                            ),
                        },
                    },
                    "required": ["doc_id"],
                },
            ),
            Tool(
                name="list_documents",
                description=(
                    "List documents in the database with their extraction status and counts. "
                    "Use to discover available documents, check extraction status before calling "
                    "extract_document, or find doc_ids for get_document/query_documents/delete_document. "
                    "Returns: {documents: [{doc_id, filename, status, upload_date, sections_count, "
                    "truths_count, entities_count, relationships_count}], count: N, total: N}. "
                    "Status values: 'parsed' (ready for extraction), 'extracting' (in progress), "
                    "'completed' (extraction done, truths available for querying). "
                    "Returns {documents: [], count: 0, total: 0} if no documents have been parsed yet."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum documents to return (1-500). Default: 100.",
                            "minimum": 1,
                            "maximum": 500,
                            "default": 100,
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Number of documents to skip (for pagination). Default: 0.",
                            "minimum": 0,
                            "default": 0,
                        },
                    },
                },
            ),
            Tool(
                name="get_document",
                description=(
                    "Get details for a single document. By default returns metadata + counts only "
                    "(lightweight). Set include_extracted_data=true to also return all truths, "
                    "entities, and relationships (can be large — prefer query_documents for targeted search). "
                    "Use this to: check extraction status, get document metadata, or retrieve full "
                    "extraction results for a specific document. "
                    "Returns: {doc_id, filename, status, upload_date, sections_count, metadata, "
                    "truths_count, entities_count, relationships_count}. "
                    "With include_extracted_data=true, also includes: "
                    "truths: [{truth_id, statement, source_section, source_page, source_paragraph, "
                    "statement_type, confidence, source_authority, related_entities}], "
                    "entities: [{entity_id, entity_name, entity_type, mention_count}], "
                    "relationships: [{relationship_id, entity_a, relationship_type, entity_b, "
                    "source_section, confidence}]. "
                    "On error: {error, type} — invalid_input if doc_id not found."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {
                            "type": "string",
                            "description": "Document ID (from parse_document or list_documents)",
                        },
                        "include_extracted_data": {
                            "type": "boolean",
                            "description": (
                                "If true, include full truths/entities/relationships arrays. "
                                "Default false (metadata + counts only). Set true only when you "
                                "need the complete extraction output."
                            ),
                            "default": False,
                        },
                    },
                    "required": ["doc_id"],
                },
            ),
            Tool(
                name="delete_document",
                description=(
                    "Delete a document and ALL associated extracted data "
                    "(truths, entities, relationships, sections). "
                    "This is irreversible. Use for data lifecycle management "
                    "or when a document should no longer be queryable. "
                    "Returns: {deleted, filename, status}. "
                    "On error: {error, type} — e.g., invalid_input if doc_id not found."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {
                            "type": "string",
                            "description": "Document ID to delete (from parse_document or list_documents)",
                        }
                    },
                    "required": ["doc_id"],
                },
            ),
            Tool(
                name="query_documents",
                description=(
                    "Search extracted truths using natural language. This is the primary tool "
                    "for finding specific information across all parsed documents. "
                    "Uses semantic search (embeddings) with automatic FTS5/keyword fallback. "
                    "Requires at least one document to have been extracted first (status 'completed'). "
                    "Returns up to 'limit' results sorted by relevance, each with full citations "
                    "(document, section, page, paragraph). "
                    "Optionally scope to specific documents using doc_ids (from list_documents). "
                    "Returns: {results: [{truth_id, statement, similarity (float or null if keyword "
                    "fallback), source: {document, section, page, paragraph}, document_date, "
                    "statement_type, confidence, source_authority, related_entities}], count: N}. "
                    "Returns {results: [], count: 0} if no matching truths found or no extractions exist. "
                    "For entity resolution, combine with get_entity_aliases."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Natural language query, e.g., 'What encryption methods are used?' "
                                "or 'customer data storage locations'"
                            ),
                        },
                        "doc_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Optional. Limit search to specific documents by doc_id. "
                                "Get doc_ids from list_documents or parse_document."
                            ),
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results to return (1-100). Default: 20.",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_entity_aliases",
                description=(
                    "Find potential aliases for a named entity (populated during extraction). "
                    "Use when consolidating entities across documents or resolving ambiguous "
                    "references (e.g., is 'CRM system' the same as 'Salesforce'?). "
                    "Entity names must match exactly — get valid names from get_document entities[] "
                    "or query_documents related_entities[]. "
                    "Returns: {entity, potential_aliases: [{entity, confidence, evidence}], "
                    "definitely_not: [{entity, evidence}]}. "
                    "Returns empty arrays if entity not found or has no extracted aliases. "
                    "This is NOT a search tool — use query_documents for natural language search."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entity_name": {
                            "type": "string",
                            "description": "Exact entity name to look up (e.g., 'customer_database')",
                        }
                    },
                    "required": ["entity_name"],
                },
            ),
            Tool(
                name="export_assessment",
                description=(
                    "Export all extracted data as a deliverable file. "
                    "Use after extraction is complete to produce output for downstream consumption. "
                    "json: machine-readable, includes all truths/entities/relationships across all documents. "
                    "sqlite: full database copy, queryable with SQL — largest but most flexible. "
                    "markdown: human-readable report with sections — suitable for review/sharing. "
                    "Returns: {exported_to, format}. "
                    "On error: {error, type} — invalid_input for unknown format. "
                    "The output_path directory must exist and be writable by the server process."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "format": {
                            "type": "string",
                            "enum": ["json", "sqlite", "markdown"],
                            "description": "Export format: 'json' (machine-readable), 'sqlite' (SQL-queryable), 'markdown' (human-readable)",
                        },
                        "output_path": {
                            "type": "string",
                            "description": "Absolute path to save the export file (directory must exist)",
                        },
                    },
                    "required": ["format", "output_path"],
                },
            ),
            Tool(
                name="resolve_technology_name",
                description=(
                    "Resolve a raw technology string to its canonical name using the "
                    "built-in technology terminology resource. Deterministic (no LLM). "
                    "Handles: aliases ('ELK Stack' → 'Elasticsearch (Elastic Stack)'), "
                    "abbreviations ('PG' → 'PostgreSQL'), version stripping ('PostgreSQL 15.3' → "
                    "'PostgreSQL', version '15.3'), typo correction (fuzzy, 0.85 threshold), "
                    "renames ('Azure AD' → 'Microsoft Entra ID'). "
                    "Returns: {canonical_name (null if no match), original, version, category, "
                    "match_method ('exact'|'fuzzy'|null), confidence (0.0-1.0), disambiguation_note}. "
                    "Use before storing technology names to ensure consistency across documents."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "raw_name": {
                            "type": "string",
                            "description": "Raw technology string from a source document (e.g., 'ELK Stack', 'PostgreSQL 15.3', 'Azure AD')",
                        }
                    },
                    "required": ["raw_name"],
                },
            ),
            Tool(
                name="suggest_terminology_addition",
                description=(
                    "Queue a terminology addition suggestion for human review. "
                    "Called when an agent encounters a technology name not in the terminology table "
                    "and resolves it via semantic dedup. Persists the suggestion in the database — "
                    "does NOT auto-add to the terminology file. "
                    "Returns: {canonical_name, aliases, category, persisted (bool), suggestion_id}. "
                    "Only use this after resolve_technology_name returns null canonical_name."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "raw_string": {
                            "type": "string",
                            "description": "The unresolved technology string from the source document",
                        },
                        "resolved_canonical": {
                            "type": "string",
                            "description": "What the agent resolved it to via semantic dedup (optional)",
                        },
                        "context": {
                            "type": "string",
                            "description": "A snippet from the source document providing usage context (optional)",
                        },
                    },
                    "required": ["raw_string"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        """Handle tool calls."""
        try:
            return await _dispatch_tool(name, arguments)
        except FileNotFoundError as e:
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps({
                    "error": str(e),
                    "type": "file_not_found",
                }))],
                isError=True,
            )
        except (ValueError, KeyError, TypeError) as e:
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps({
                    "error": str(e),
                    "type": "invalid_input",
                }))],
                isError=True,
            )
        except Exception as e:
            logger.error(f"Tool {name} failed: {type(e).__name__}: {e}", exc_info=True)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps({
                    "error": f"{type(e).__name__}: {e}",
                    "type": "internal_error",
                }))],
                isError=True,
            )

    def _require_str(arguments: dict, key: str, max_length: int = 10000) -> str:
        """Validate a required string parameter."""
        val = arguments.get(key)
        if not val or not isinstance(val, str) or not val.strip():
            raise ValueError(f"'{key}' is required and must be a non-empty string")
        val = val.strip()
        if len(val) > max_length:
            raise ValueError(f"'{key}' exceeds maximum length of {max_length} characters")
        return val

    async def _dispatch_tool(name: str, arguments: dict):
        """Route tool calls to implementations."""
        if name == "parse_document":
            file_path = _require_str(arguments, "file_path")
            result = await parse_document_tool(
                file_path=file_path,
                db_path=DEFAULT_DB_PATH,
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "extract_document":
            doc_id = _require_str(arguments, "doc_id", max_length=200)
            analysis_context = arguments.get("analysis_context")
            if analysis_context and analysis_context not in ("stride_threat_modeling", "tprm_vendor_assessment"):
                raise ValueError(
                    f"Invalid analysis_context '{analysis_context}'. "
                    "Must be 'stride_threat_modeling' or 'tprm_vendor_assessment'."
                )
            result = await extract_document_tool(
                doc_id=doc_id,
                db_path=DEFAULT_DB_PATH,
                extraction_model=arguments.get("extraction_model"),
                analysis_context=analysis_context,
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "list_documents":
            limit = arguments.get("limit", 100)
            if not isinstance(limit, int) or limit < 1:
                limit = 100
            limit = min(limit, 500)
            offset = arguments.get("offset", 0)
            if not isinstance(offset, int) or offset < 0:
                offset = 0
            result = await list_documents_tool(
                db_path=DEFAULT_DB_PATH, limit=limit, offset=offset,
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "get_document":
            doc_id = _require_str(arguments, "doc_id", max_length=200)
            include_extracted = bool(arguments.get("include_extracted_data", False))
            result = await get_document_tool(
                doc_id=doc_id,
                db_path=DEFAULT_DB_PATH,
                include_extracted_data=include_extracted,
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "delete_document":
            doc_id = _require_str(arguments, "doc_id", max_length=200)
            result = await delete_document_tool(
                doc_id=doc_id,
                db_path=DEFAULT_DB_PATH,
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "query_documents":
            query = _require_str(arguments, "query")
            from .query import QueryEngine
            from .embeddings import EmbeddingService

            db = Database(DEFAULT_DB_PATH)
            await db.initialize()

            try:
                embedding_service = EmbeddingService()
            except ImportError:
                embedding_service = None

            limit = arguments.get("limit", 20)
            if not isinstance(limit, int) or limit < 1:
                limit = 20
            limit = min(limit, 100)

            query_engine = QueryEngine(db, embedding_service=embedding_service)
            results = await query_engine.query(
                query,
                doc_ids=arguments.get("doc_ids"),
                top_k=limit,
            )
            return [TextContent(type="text", text=json.dumps({
                "results": results,
                "count": len(results),
            }))]

        elif name == "get_entity_aliases":
            entity_name = _require_str(arguments, "entity_name", max_length=500)
            from .query import QueryEngine
            from .embeddings import EmbeddingService

            db = Database(DEFAULT_DB_PATH)
            await db.initialize()

            try:
                embedding_service = EmbeddingService()
            except ImportError:
                embedding_service = None

            query_engine = QueryEngine(db, embedding_service=embedding_service)
            result = await query_engine.get_entity_aliases(entity_name)
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "export_assessment":
            format_type = _require_str(arguments, "format", max_length=20)
            output_path_str = _require_str(arguments, "output_path")

            # Path traversal protection for export output
            from .tools import ALLOWED_DOC_DIRS
            output_path = Path(output_path_str).resolve()
            if ALLOWED_DOC_DIRS:
                if not any(output_path == d or output_path.is_relative_to(d) for d in ALLOWED_DOC_DIRS):
                    raise ValueError("Access denied: export path is outside allowed directories")

            from .export import AssessmentExporter

            db = Database(DEFAULT_DB_PATH)
            await db.initialize()
            exporter = AssessmentExporter(db)

            if format_type == "json":
                result_path = await exporter.export_json(output_path)
            elif format_type == "sqlite":
                result_path = await exporter.export_sqlite(output_path)
            elif format_type == "markdown":
                result_path = await exporter.export_markdown(output_path)
            else:
                raise ValueError(f"Unknown format: {format_type}")

            return [TextContent(
                type="text",
                text=json.dumps({"exported_to": str(result_path), "format": format_type}),
            )]

        elif name == "resolve_technology_name":
            raw_name = _require_str(arguments, "raw_name", max_length=500)
            result = await resolve_technology_name_tool(raw_name=raw_name)
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "suggest_terminology_addition":
            raw_string = _require_str(arguments, "raw_string", max_length=500)
            result = await suggest_terminology_addition_tool(
                raw_string=raw_string,
                resolved_canonical=arguments.get("resolved_canonical"),
                context=arguments.get("context"),
                db_path=DEFAULT_DB_PATH,
            )
            return [TextContent(type="text", text=json.dumps(result))]

        else:
            raise ValueError(f"Unknown tool: {name}")

    return server


async def main():
    """Run the MCP server."""
    logging.basicConfig(level=logging.INFO)
    server = create_server()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
