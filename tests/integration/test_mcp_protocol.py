"""MCP protocol-level integration test.

Verifies the STDIO server correctly handles MCP protocol messages:
tool listing, tool invocation, and structured error responses.

The MCP stdio surface exposes only resolve_technology_name.
All document processing is via the HTTP API (/extract-stateless).
"""

import json
import pytest
from mcp.types import ListToolsRequest, CallToolRequest  # noqa: F401 (CallToolRequest used in _call_tool)

from document_logic_mcp.server import create_server


EXPECTED_TOOLS = {
    "resolve_technology_name",
}


@pytest.fixture
def server():
    """Create a fresh MCP server instance."""
    return create_server()


async def _list_tools(server):
    """Invoke the list_tools handler via MCP protocol."""
    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    return result.root.tools


async def _call_tool(server, name: str, arguments: dict):
    """Invoke a tool via MCP protocol."""
    handler = server.request_handlers[CallToolRequest]
    result = await handler(CallToolRequest(
        method="tools/call",
        params={"name": name, "arguments": arguments},
    ))
    return result.root


class TestToolListing:
    """Verify tools/list returns all expected tools with valid schemas."""

    @pytest.mark.asyncio
    async def test_all_tools_registered(self, server):
        """Server must expose exactly the expected set of tools."""
        tools = await _list_tools(server)
        tool_names = {t.name for t in tools}
        assert tool_names == EXPECTED_TOOLS, (
            f"Missing: {EXPECTED_TOOLS - tool_names}, "
            f"Extra: {tool_names - EXPECTED_TOOLS}"
        )

    @pytest.mark.asyncio
    async def test_tool_count(self, server):
        """Server must expose exactly 1 tool (resolve_technology_name)."""
        tools = await _list_tools(server)
        assert len(tools) == 1

    @pytest.mark.asyncio
    async def test_tools_have_descriptions(self, server):
        """Every tool must have a non-empty description."""
        tools = await _list_tools(server)
        for tool in tools:
            assert tool.description and len(tool.description.strip()) > 0, (
                f"Tool '{tool.name}' has empty description"
            )

    @pytest.mark.asyncio
    async def test_tools_have_input_schemas(self, server):
        """Every tool must declare an inputSchema with type=object."""
        tools = await _list_tools(server)
        for tool in tools:
            schema = tool.inputSchema
            assert schema is not None, f"Tool '{tool.name}' missing inputSchema"
            assert schema.get("type") == "object", (
                f"Tool '{tool.name}' inputSchema type must be 'object'"
            )


class TestToolInvocation:
    """Verify tools/call returns structured responses and errors."""

    @pytest.mark.asyncio
    async def test_missing_required_param_returns_error(self, server):
        """Calling resolve_technology_name without raw_name returns isError."""
        result = await _call_tool(server, "resolve_technology_name", {})
        assert result.isError is True
        error_text = result.content[0].text
        assert "raw_name" in error_text

    @pytest.mark.asyncio
    async def test_resolve_technology_name_returns_json(self, server):
        """resolve_technology_name returns valid JSON with canonical_name field."""
        result = await _call_tool(server, "resolve_technology_name", {
            "raw_name": "PostgreSQL"
        })
        assert result.isError is not True
        data = json.loads(result.content[0].text)
        assert "canonical_name" in data

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_structured_error(self, server):
        """Calling an unknown tool returns structured JSON with type=invalid_input."""
        result = await _call_tool(server, "nonexistent_tool", {})
        assert result.isError is True
        error_data = json.loads(result.content[0].text)
        assert "error" in error_data
        assert "type" in error_data
