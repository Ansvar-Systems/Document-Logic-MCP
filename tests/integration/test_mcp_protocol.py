"""MCP protocol-level integration test.

Verifies the STDIO server correctly handles MCP protocol messages:
tool listing, tool invocation, and structured error responses.
"""

import json
import pytest
from unittest.mock import patch
from mcp.types import ListToolsRequest, CallToolRequest

from document_logic_mcp.server import create_server


EXPECTED_TOOLS = {
    "parse_document",
    "extract_document",
    "list_documents",
    "get_document",
    "delete_document",
    "query_documents",
    "get_entity_aliases",
    "export_assessment",
    "resolve_technology_name",
    "suggest_terminology_addition",
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
        """Server must expose exactly 10 tools."""
        tools = await _list_tools(server)
        assert len(tools) == 10

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

    @pytest.mark.asyncio
    async def test_parse_document_schema_requires_explicit_scope(self, server):
        """Schema must not validate conversation-scope requests without an owner."""
        tools = await _list_tools(server)
        parse_tool = next(tool for tool in tools if tool.name == "parse_document")
        schema = parse_tool.inputSchema
        assert "scope" in schema.get("required", [])
        assert schema.get("allOf"), "parse_document schema must declare conditional requirements"
        assert schema["allOf"][0]["then"]["required"] == ["owner_user_id"]


class TestToolInvocation:
    """Verify tools/call returns structured responses and errors."""

    @pytest.mark.asyncio
    async def test_missing_required_param_returns_error(self, server):
        """Calling parse_document without file_path returns isError with message."""
        result = await _call_tool(server, "parse_document", {})
        assert result.isError is True
        error_text = result.content[0].text
        # MCP SDK schema validation catches missing required params
        assert "file_path" in error_text

    @pytest.mark.asyncio
    async def test_list_documents_returns_json(self, server, tmp_path):
        """list_documents should return valid JSON with documents array."""
        db_path = tmp_path / "test.db"
        with patch("document_logic_mcp.server.DEFAULT_DB_PATH", db_path):
            result = await _call_tool(server, "list_documents", {"org_id": "org-1"})
        assert result.isError is not True
        data = json.loads(result.content[0].text)
        assert "documents" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_handler_error_returns_structured_json(self, server, tmp_path):
        """Handler-level errors (e.g., file not found) return structured JSON."""
        db_path = tmp_path / "test.db"
        with patch("document_logic_mcp.server.DEFAULT_DB_PATH", db_path):
            result = await _call_tool(server, "parse_document", {
                "file_path": "/nonexistent/path/doc.pdf",
                "org_id": "org-1",
                "scope": "conversation",
                "owner_user_id": "user-1",
            })
        assert result.isError is True
        error_data = json.loads(result.content[0].text)
        assert "error" in error_data
        assert "type" in error_data
