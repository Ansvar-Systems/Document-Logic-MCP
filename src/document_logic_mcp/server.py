"""Document-Logic MCP Server.

Workflow: parse_document → extract_document → query_documents / export_assessment
"""

import json
import logging
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from .tools import parse_document_tool, extract_document_tool
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
                    "Use the returned doc_id for extract_document."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": (
                                "Absolute path to the document file. "
                                "Supported formats: .pdf, .docx, .doc, .json"
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
                    "SLOW (1-5 minutes) — blocks until complete. Requires parse_document first. "
                    "Three-pass pipeline: "
                    "Pass 1: document overview (purpose, topics, entities). "
                    "Pass 2: per-section truths, entities, relationships. "
                    "Pass 3 (optional): cross-section synthesis — activated by analysis_context. "
                    "Returns: {doc_id, status, truths_extracted, entities_found, relationships_found, "
                    "overview, truths[], entities[], relationships[], synthesis (when analysis_context set)}."
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
                                "Optional domain context that activates domain-specific "
                                "extraction (Pass 2) and cross-section synthesis (Pass 3). "
                                "'stride_threat_modeling': trust boundaries, data flow directionality, "
                                "implicit negatives, ambiguity flags. "
                                "'tprm_vendor_assessment': certifications, subprocessors, SLAs, "
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
                name="query_documents",
                description=(
                    "Query extracted truths using natural language. Uses semantic search "
                    "(embeddings) with keyword fallback. Returns up to 20 results sorted by "
                    "relevance, each with full citations. "
                    "Returns: [{truth_id, statement, similarity, source: {document, section, page, "
                    "paragraph}, document_date, statement_type, confidence, source_authority, "
                    "related_entities}]."
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
                        }
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_entity_aliases",
                description=(
                    "Find potential aliases for a named entity. Useful for entity resolution — "
                    "checking if different names refer to the same system, person, or organization. "
                    "Returns: {entity, potential_aliases: [{entity, confidence, evidence}], "
                    "definitely_not: [{entity, evidence}]}."
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

        elif name == "query_documents":
            from .query import QueryEngine
            from .embeddings import EmbeddingService

            db = Database(DEFAULT_DB_PATH)

            try:
                embedding_service = EmbeddingService()
            except ImportError:
                embedding_service = None

            query_engine = QueryEngine(db, embedding_service=embedding_service)
            results = await query_engine.query(arguments["query"])
            return [TextContent(type="text", text=json.dumps(results))]

        elif name == "get_entity_aliases":
            from .query import QueryEngine
            from .embeddings import EmbeddingService

            db = Database(DEFAULT_DB_PATH)

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
