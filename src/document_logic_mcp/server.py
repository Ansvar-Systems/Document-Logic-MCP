"""Document-Logic MCP server."""

import json
import logging
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from .database import Database
from .export import AssessmentExporter
from .query import QueryEngine
from .tools import (
    ALLOWED_DOC_DIRS,
    delete_document_tool,
    extract_document_tool,
    get_document_tool,
    list_documents_tool,
    parse_document_tool,
    resolve_technology_name_tool,
    suggest_terminology_addition_tool,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/assessment.db")
_ANALYSIS_CONTEXTS = [
    "stride_threat_modeling",
    "tprm_vendor_assessment",
    "compliance_mapping",
]


def create_server() -> Server:
    """Create and configure the Document-Logic MCP server."""
    server = Server("document-logic-mcp")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="parse_document",
                description="Parse a document and store it in the tenant-scoped document store.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to the document file."},
                        "org_id": {"type": "string", "description": "Tenant organization identifier."},
                        "owner_user_id": {
                            "type": "string",
                            "description": "Required when scope=conversation.",
                        },
                        "scope": {
                            "type": "string",
                            "enum": ["conversation", "organization"],
                            "description": "Storage scope for the parsed document.",
                        },
                        "allow_org_write": {
                            "type": "boolean",
                            "default": False,
                            "description": "Required for organization-scoped writes.",
                        },
                    },
                    "required": ["file_path", "org_id", "scope"],
                    "allOf": [
                        {
                            "if": {
                                "required": ["scope"],
                                "properties": {
                                    "scope": {"const": "conversation"},
                                },
                            },
                            "then": {"required": ["owner_user_id"]},
                        },
                    ],
                },
            ),
            Tool(
                name="extract_document",
                description="Run LLM extraction against a parsed document visible to the caller.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string", "description": "Document ID returned by parse_document."},
                        "org_id": {"type": "string", "description": "Tenant organization identifier."},
                        "user_id": {"type": "string", "description": "Caller identity for conversation-scoped access."},
                        "allow_org_write": {
                            "type": "boolean",
                            "default": False,
                            "description": "Required for organization-scoped writes.",
                        },
                        "analysis_context": {"type": "string", "enum": _ANALYSIS_CONTEXTS},
                        "extraction_model": {"type": "string"},
                    },
                    "required": ["doc_id", "org_id"],
                },
            ),
            Tool(
                name="list_documents",
                description="List documents visible to the caller within one organization.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "org_id": {"type": "string", "description": "Tenant organization identifier."},
                        "user_id": {"type": "string", "description": "Caller identity for conversation-scoped access."},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                        "offset": {"type": "integer", "minimum": 0, "default": 0},
                    },
                    "required": ["org_id"],
                },
            ),
            Tool(
                name="get_document",
                description="Get metadata or extracted data for one accessible document.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string", "description": "Document ID."},
                        "org_id": {"type": "string", "description": "Tenant organization identifier."},
                        "user_id": {"type": "string", "description": "Caller identity for conversation-scoped access."},
                        "include_extracted_data": {"type": "boolean", "default": False},
                    },
                    "required": ["doc_id", "org_id"],
                },
            ),
            Tool(
                name="delete_document",
                description="Delete an accessible document and all associated extracted data.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string", "description": "Document ID."},
                        "org_id": {"type": "string", "description": "Tenant organization identifier."},
                        "user_id": {"type": "string", "description": "Caller identity for conversation-scoped access."},
                        "allow_org_write": {
                            "type": "boolean",
                            "default": False,
                            "description": "Required for organization-scoped writes.",
                        },
                    },
                    "required": ["doc_id", "org_id"],
                },
            ),
            Tool(
                name="query_documents",
                description="Search truths from documents visible to the caller.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language query."},
                        "org_id": {"type": "string", "description": "Tenant organization identifier."},
                        "user_id": {"type": "string", "description": "Caller identity for conversation-scoped access."},
                        "doc_ids": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    },
                    "required": ["query", "org_id"],
                },
            ),
            Tool(
                name="get_entity_aliases",
                description="Look up entity aliases within the caller's accessible documents.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entity_name": {"type": "string", "description": "Exact entity name to look up."},
                        "org_id": {"type": "string", "description": "Tenant organization identifier."},
                        "user_id": {"type": "string", "description": "Caller identity for conversation-scoped access."},
                    },
                    "required": ["entity_name", "org_id"],
                },
            ),
            Tool(
                name="export_assessment",
                description="Export only the documents visible to the caller.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "format": {"type": "string", "enum": ["json", "sqlite", "markdown"]},
                        "output_path": {"type": "string", "description": "Absolute export path."},
                        "org_id": {"type": "string", "description": "Tenant organization identifier."},
                        "user_id": {"type": "string", "description": "Caller identity for conversation-scoped access."},
                    },
                    "required": ["format", "output_path", "org_id"],
                },
            ),
            Tool(
                name="resolve_technology_name",
                description="Resolve a raw technology string to a canonical name.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "raw_name": {"type": "string", "description": "Raw technology string."},
                    },
                    "required": ["raw_name"],
                },
            ),
            Tool(
                name="suggest_terminology_addition",
                description="Persist a terminology suggestion with tenant attribution for review.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "raw_string": {"type": "string", "description": "Unresolved technology string."},
                        "resolved_canonical": {"type": "string"},
                        "context": {"type": "string"},
                        "org_id": {"type": "string", "description": "Tenant organization identifier."},
                        "user_id": {"type": "string", "description": "Caller identity."},
                    },
                    "required": ["raw_string", "org_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            return await _dispatch_tool(name, arguments)
        except FileNotFoundError as exc:
            return _error_result(str(exc), "file_not_found")
        except PermissionError as exc:
            return _error_result(str(exc), "permission_denied")
        except (ValueError, KeyError, TypeError) as exc:
            return _error_result(str(exc), "invalid_input")
        except Exception as exc:
            logger.error("Tool %s failed: %s: %s", name, type(exc).__name__, exc, exc_info=True)
            return _error_result(f"{type(exc).__name__}: {exc}", "internal_error")

    def _require_str(arguments: dict, key: str, max_length: int = 10000) -> str:
        value = arguments.get(key)
        if not value or not isinstance(value, str) or not value.strip():
            raise ValueError(f"'{key}' is required and must be a non-empty string")
        value = value.strip()
        if len(value) > max_length:
            raise ValueError(f"'{key}' exceeds maximum length of {max_length} characters")
        return value

    def _optional_str(arguments: dict, key: str, max_length: int = 10000) -> str | None:
        value = arguments.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"'{key}' must be a string when provided")
        value = value.strip()
        if not value:
            return None
        if len(value) > max_length:
            raise ValueError(f"'{key}' exceeds maximum length of {max_length} characters")
        return value

    def _optional_bool(arguments: dict, key: str) -> bool:
        value = arguments.get(key, False)
        if isinstance(value, bool):
            return value
        raise ValueError(f"'{key}' must be a boolean when provided")

    async def _dispatch_tool(name: str, arguments: dict):
        if name == "parse_document":
            result = await parse_document_tool(
                file_path=_require_str(arguments, "file_path"),
                db_path=DEFAULT_DB_PATH,
                org_id=_require_str(arguments, "org_id", max_length=256),
                scope=_require_str(arguments, "scope", max_length=32),
                owner_user_id=_optional_str(arguments, "owner_user_id", max_length=256),
                allow_org_write=_optional_bool(arguments, "allow_org_write"),
            )
            return _success_result(result)

        if name == "extract_document":
            analysis_context = arguments.get("analysis_context")
            if analysis_context and analysis_context not in _ANALYSIS_CONTEXTS:
                raise ValueError(
                    f"Invalid analysis_context '{analysis_context}'. Must be one of: {', '.join(_ANALYSIS_CONTEXTS)}."
                )
            result = await extract_document_tool(
                doc_id=_require_str(arguments, "doc_id", max_length=200),
                db_path=DEFAULT_DB_PATH,
                extraction_model=_optional_str(arguments, "extraction_model", max_length=200),
                analysis_context=analysis_context,
                org_id=_require_str(arguments, "org_id", max_length=256),
                user_id=_optional_str(arguments, "user_id", max_length=256),
                allow_org_write=_optional_bool(arguments, "allow_org_write"),
            )
            return _success_result(result)

        if name == "list_documents":
            limit = arguments.get("limit", 100)
            if not isinstance(limit, int) or limit < 1:
                limit = 100
            offset = arguments.get("offset", 0)
            if not isinstance(offset, int) or offset < 0:
                offset = 0
            result = await list_documents_tool(
                db_path=DEFAULT_DB_PATH,
                org_id=_require_str(arguments, "org_id", max_length=256),
                user_id=_optional_str(arguments, "user_id", max_length=256),
                limit=min(limit, 500),
                offset=offset,
            )
            return _success_result(result)

        if name == "get_document":
            result = await get_document_tool(
                doc_id=_require_str(arguments, "doc_id", max_length=200),
                db_path=DEFAULT_DB_PATH,
                include_extracted_data=_optional_bool(arguments, "include_extracted_data"),
                org_id=_require_str(arguments, "org_id", max_length=256),
                user_id=_optional_str(arguments, "user_id", max_length=256),
            )
            return _success_result(result)

        if name == "delete_document":
            result = await delete_document_tool(
                doc_id=_require_str(arguments, "doc_id", max_length=200),
                db_path=DEFAULT_DB_PATH,
                org_id=_require_str(arguments, "org_id", max_length=256),
                user_id=_optional_str(arguments, "user_id", max_length=256),
                allow_org_write=_optional_bool(arguments, "allow_org_write"),
            )
            return _success_result(result)

        if name == "query_documents":
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

            query_engine = QueryEngine(db, embedding_service=embedding_service)
            results = await query_engine.query(
                _require_str(arguments, "query"),
                org_id=_require_str(arguments, "org_id", max_length=256),
                user_id=_optional_str(arguments, "user_id", max_length=256),
                doc_ids=arguments.get("doc_ids"),
                top_k=min(limit, 100),
            )
            return _success_result({"results": results, "count": len(results)})

        if name == "get_entity_aliases":
            from .embeddings import EmbeddingService

            db = Database(DEFAULT_DB_PATH)
            await db.initialize()
            try:
                embedding_service = EmbeddingService()
            except ImportError:
                embedding_service = None

            query_engine = QueryEngine(db, embedding_service=embedding_service)
            result = await query_engine.get_entity_aliases(
                _require_str(arguments, "entity_name", max_length=500),
                org_id=_require_str(arguments, "org_id", max_length=256),
                user_id=_optional_str(arguments, "user_id", max_length=256),
            )
            return _success_result(result)

        if name == "export_assessment":
            format_type = _require_str(arguments, "format", max_length=20)
            output_path_str = _require_str(arguments, "output_path")
            output_path = Path(output_path_str).resolve()
            if ALLOWED_DOC_DIRS:
                if not any(output_path == directory or output_path.is_relative_to(directory) for directory in ALLOWED_DOC_DIRS):
                    raise ValueError("Access denied: export path is outside allowed directories")

            db = Database(DEFAULT_DB_PATH)
            await db.initialize()
            exporter = AssessmentExporter(
                db,
                org_id=_require_str(arguments, "org_id", max_length=256),
                user_id=_optional_str(arguments, "user_id", max_length=256),
            )

            if format_type == "json":
                result_path = await exporter.export_json(output_path)
            elif format_type == "sqlite":
                result_path = await exporter.export_sqlite(output_path)
            elif format_type == "markdown":
                result_path = await exporter.export_markdown(output_path)
            else:
                raise ValueError(f"Unknown format: {format_type}")
            return _success_result({"exported_to": str(result_path), "format": format_type})

        if name == "resolve_technology_name":
            result = await resolve_technology_name_tool(_require_str(arguments, "raw_name", max_length=500))
            return _success_result(result)

        if name == "suggest_terminology_addition":
            result = await suggest_terminology_addition_tool(
                raw_string=_require_str(arguments, "raw_string", max_length=500),
                resolved_canonical=_optional_str(arguments, "resolved_canonical", max_length=500),
                context=_optional_str(arguments, "context", max_length=4000),
                db_path=DEFAULT_DB_PATH,
                org_id=_require_str(arguments, "org_id", max_length=256),
                user_id=_optional_str(arguments, "user_id", max_length=256),
            )
            return _success_result(result)

        raise ValueError(f"Unknown tool: {name}")

    return server


def _success_result(payload: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload))]


def _error_result(message: str, error_type: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps({"error": message, "type": error_type}))],
        isError=True,
    )


async def main():
    logging.basicConfig(level=logging.INFO)
    server = create_server()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
