"""Document-Logic MCP Server."""

import logging
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from .tools import parse_document_tool, extract_document_tool

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
                description="Parse a document (PDF/DOCX) and extract structure. Fast (seconds), deterministic. Returns doc_id for extraction.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Absolute path to document file"
                        }
                    },
                    "required": ["file_path"]
                }
            ),
            Tool(
                name="extract_document",
                description="Extract truths, entities, and relationships from parsed document. Slow (minutes), LLM-based. Blocks until complete.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {
                            "type": "string",
                            "description": "Document ID from parse_document"
                        }
                    },
                    "required": ["doc_id"]
                }
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        """Handle tool calls."""
        if name == "parse_document":
            result = await parse_document_tool(
                file_path=arguments["file_path"],
                db_path=DEFAULT_DB_PATH
            )
            return [TextContent(type="text", text=str(result))]

        elif name == "extract_document":
            result = await extract_document_tool(
                doc_id=arguments["doc_id"],
                db_path=DEFAULT_DB_PATH
            )
            return [TextContent(type="text", text=str(result))]

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
