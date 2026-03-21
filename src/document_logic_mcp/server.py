"""Document-Logic MCP Server.

MCP stdio surface: resolve_technology_name only.

All document parsing and extraction is handled via the HTTP API
(POST /extract-stateless). The MCP stdio transport exposes only
resolve_technology_name, which is agent-facing and stateless.
"""

import json
import logging
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult
from .tools import resolve_technology_name_tool

logger = logging.getLogger(__name__)


def create_server() -> Server:
    """Create and configure the Document-Logic MCP server.

    Exposes only resolve_technology_name via MCP stdio. All document
    processing is handled via the HTTP API (/extract-stateless).
    """
    server = Server("document-logic-mcp")

    @server.list_tools()
    async def list_tools():
        """List available tools."""
        return [
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
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        """Handle tool calls."""
        try:
            return await _dispatch_tool(name, arguments)
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
        if name == "resolve_technology_name":
            raw_name = _require_str(arguments, "raw_name", max_length=500)
            result = await resolve_technology_name_tool(raw_name=raw_name)
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
