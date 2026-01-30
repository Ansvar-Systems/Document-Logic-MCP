"""Document-Logic MCP Server."""

import logging
from mcp.server import Server
from mcp.server.stdio import stdio_server

logger = logging.getLogger(__name__)


def create_server() -> Server:
    """Create and configure the Document-Logic MCP server."""
    server = Server("document-logic-mcp")

    @server.list_tools()
    async def list_tools():
        """List available tools."""
        return []

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
