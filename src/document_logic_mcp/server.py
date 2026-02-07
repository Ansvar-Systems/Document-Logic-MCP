"""Document-Logic MCP Server.

Workflow: parse_document → extract_document → query_documents / export_assessment
"""

import json
import logging
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from .tools import parse_document_tool, extract_document_tool, list_documents_tool, get_document_tool, delete_document_tool
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
                    "Parse a document (PDF, DOCX, or JSON) and extract structure. "
                    "Fast (seconds), deterministic. This is always the FIRST step — "
                    "call this before extract_document. "
                    "Returns: {doc_id, filename, sections_count, page_count, status, entities_preview}. "
                    "Use the returned doc_id for extract_document. "
                    "On error: {error, error_type} — e.g., file_not_found or invalid_input for unsupported format."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": (
                                "Absolute path to the document file. "
                                "Supported formats: .pdf, .docx, .json"
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
                    "Requires parse_document first. "
                    "Pass 1: document overview. Pass 2: per-section truths/entities/relationships. "
                    "Without analysis_context: returns truths/entities/relationships only (no 'synthesis' key). "
                    "With analysis_context: also runs Pass 3 cross-section synthesis, adding a 'synthesis' key "
                    "with component_registry, trust_boundaries, implicit_negatives, ambiguities. "
                    "Returns: {doc_id, status, truths_extracted, entities_found, relationships_found, "
                    "overview, truths[], entities[], relationships[], synthesis? (only when analysis_context set)}. "
                    "On error: {error, error_type}."
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
                    "List all documents in the database with their extraction status and counts. "
                    "Use to discover what documents exist, check if extraction is complete, "
                    "or find doc_ids for use with get_document or query_documents. "
                    "Returns: {documents: [{doc_id, filename, status, upload_date, sections_count, "
                    "truths_count, entities_count, relationships_count}], count: N}. "
                    "Status values: 'parsed' (ready for extraction), 'extracting' (in progress), "
                    "'completed' (extraction done)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="get_document",
                description=(
                    "Get full details for a single document including all extracted data. "
                    "Use to check extraction status, retrieve truths/entities/relationships, "
                    "or inspect what was extracted from a specific document. "
                    "Returns: {doc_id, filename, status, upload_date, sections_count, "
                    "truths_count, entities_count, relationships_count, "
                    "truths: [{truth_id, statement, source_section, source_page, source_paragraph, "
                    "statement_type, confidence, source_authority, related_entities}], "
                    "entities: [{entity_id, entity_name, entity_type, mention_count}], "
                    "relationships: [{relationship_id, entity_a, relationship_type, entity_b, "
                    "source_section, confidence}]}. "
                    "On error: {error, error_type} — e.g., invalid_input if doc_id not found."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {
                            "type": "string",
                            "description": "Document ID (from parse_document or list_documents)",
                        }
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
                    "On error: {error, error_type} — e.g., invalid_input if doc_id not found."
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
                    "Query extracted truths using natural language. Uses semantic search "
                    "(embeddings) with keyword fallback. Returns up to 20 results sorted by "
                    "relevance, each with full citations. "
                    "Optionally scope to specific documents using doc_ids. "
                    "Returns: {results: [{truth_id, statement, similarity (float or null if keyword "
                    "fallback), source: {document, section, page, paragraph}, document_date, "
                    "statement_type, confidence, source_authority, related_entities}], count: N}. "
                    "Returns {results: [], count: 0} if no truths extracted yet."
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
                    "Returns: {entity, potential_aliases: [{entity, confidence, evidence}], "
                    "definitely_not: [{entity, evidence}]}. "
                    "Returns empty arrays if entity not found or has no extracted aliases."
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
                    "json: machine-readable, includes all truths/entities/relationships. "
                    "sqlite: full database copy, queryable with SQL. "
                    "markdown: human-readable report with sections. "
                    "Returns: {exported_to, format}."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "format": {
                            "type": "string",
                            "enum": ["json", "sqlite", "markdown"],
                            "description": "Export format",
                        },
                        "output_path": {
                            "type": "string",
                            "description": "Absolute path to save the export file",
                        },
                    },
                    "required": ["format", "output_path"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        """Handle tool calls."""
        try:
            return await _dispatch_tool(name, arguments)
        except FileNotFoundError as e:
            return [TextContent(type="text", text=json.dumps({
                "error": str(e),
                "error_type": "file_not_found",
            }))]
        except ValueError as e:
            return [TextContent(type="text", text=json.dumps({
                "error": str(e),
                "error_type": "invalid_input",
            }))]
        except Exception as e:
            logger.error(f"Tool {name} failed: {type(e).__name__}: {e}", exc_info=True)
            return [TextContent(type="text", text=json.dumps({
                "error": f"{type(e).__name__}: {e}",
                "error_type": "internal_error",
            }))]

    async def _dispatch_tool(name: str, arguments: dict):
        """Route tool calls to implementations."""
        if name == "parse_document":
            result = await parse_document_tool(
                file_path=arguments["file_path"],
                db_path=DEFAULT_DB_PATH,
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "extract_document":
            result = await extract_document_tool(
                doc_id=arguments["doc_id"],
                db_path=DEFAULT_DB_PATH,
                extraction_model=arguments.get("extraction_model"),
                analysis_context=arguments.get("analysis_context"),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "list_documents":
            result = await list_documents_tool(db_path=DEFAULT_DB_PATH)
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "get_document":
            result = await get_document_tool(
                doc_id=arguments["doc_id"],
                db_path=DEFAULT_DB_PATH,
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "delete_document":
            result = await delete_document_tool(
                doc_id=arguments["doc_id"],
                db_path=DEFAULT_DB_PATH,
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "query_documents":
            from .query import QueryEngine
            from .embeddings import EmbeddingService

            db = Database(DEFAULT_DB_PATH)
            await db.initialize()

            try:
                embedding_service = EmbeddingService()
            except ImportError:
                embedding_service = None

            query_engine = QueryEngine(db, embedding_service=embedding_service)
            results = await query_engine.query(
                arguments["query"],
                doc_ids=arguments.get("doc_ids"),
            )
            return [TextContent(type="text", text=json.dumps({
                "results": results,
                "count": len(results),
            }))]

        elif name == "get_entity_aliases":
            from .query import QueryEngine
            from .embeddings import EmbeddingService

            db = Database(DEFAULT_DB_PATH)
            await db.initialize()

            try:
                embedding_service = EmbeddingService()
            except ImportError:
                embedding_service = None

            query_engine = QueryEngine(db, embedding_service=embedding_service)
            result = await query_engine.get_entity_aliases(arguments["entity_name"])
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "export_assessment":
            from .export import AssessmentExporter

            db = Database(DEFAULT_DB_PATH)
            await db.initialize()
            exporter = AssessmentExporter(db)

            format_type = arguments["format"]
            output_path = Path(arguments["output_path"])

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
