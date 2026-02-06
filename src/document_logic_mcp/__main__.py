"""Entry point for running Document-Logic MCP server.

Usage:
    python -m document_logic_mcp          # Run MCP server (STDIO transport)
    python -m document_logic_mcp --http   # Run HTTP/SSE server
"""

import asyncio
import sys


def main():
    if "--http" in sys.argv:
        import uvicorn
        import os

        from .http_server import app  # noqa: F401

        port = int(os.getenv("PORT", "3000"))
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        from .server import main as mcp_main

        asyncio.run(mcp_main())


main()
