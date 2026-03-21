"""Tests for POST /extract stateless endpoint."""

import os
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

# Remove MCP_API_KEY so auth is skipped (dev mode)
os.environ.pop("MCP_API_KEY", None)

from document_logic_mcp.http_server import app
from document_logic_mcp.extraction.pipeline import ExtractionOutput


def _make_section(i: int) -> dict:
    return {
        "section_ref": f"sec-{i}",
        "title": f"Section {i}",
        "content": f"Content for section {i}.",
        "section_index": i,
        "page_start": i,
        "page_end": i,
        "parent_ref": None,
    }


def _valid_payload(n_sections: int = 1) -> dict:
    return {
        "sections": [_make_section(i) for i in range(n_sections)],
        "filename": "test.pdf",
        "schema_version": "2.0.0",
        "input_hash": "abc123",
    }


@pytest.mark.asyncio
async def test_extract_rejects_too_many_sections():
    """201 sections exceeds the default cap of 200 → 422."""
    payload = _valid_payload(n_sections=201)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/extract-stateless", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert "sections" in body["detail"].lower()


@pytest.mark.asyncio
async def test_extract_rejects_missing_required_fields():
    """Missing filename → 422 from Pydantic validation."""
    payload = {
        "sections": [_make_section(0)],
        # filename omitted
        "schema_version": "2.0.0",
        "input_hash": "abc123",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/extract-stateless", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_extract_returns_200_with_valid_sections():
    """Valid payload with mocked run_extraction → 200 + X-Extraction-Schema-Version header."""
    mock_output = ExtractionOutput(
        truths=[{"statement": "Test fact", "source_section": "Section 0", "source_page": 0, "statement_type": "fact", "confidence": 0.9}],
        entities=[],
        relationships=[],
        overview="Test document purpose",
        synthesis=None,
        metadata={
            "schema_version": "2.0.0",
            "extractor_version": "2.0.0",
            "model_used": None,
            "input_hash": "abc123",
            "section_count": 1,
            "truths_count": 1,
            "entities_count": 0,
            "relationships_count": 0,
            "duration_seconds": 0.01,
            "warnings": [],
        },
    )

    payload = _valid_payload(n_sections=1)

    with patch(
        "document_logic_mcp.http_server.run_extraction",
        new=AsyncMock(return_value=mock_output),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/extract-stateless", json=payload)

    assert response.status_code == 200
    assert response.headers.get("x-extraction-schema-version") == "2.0.0"
    body = response.json()
    assert "truths" in body
    assert "entities" in body
    assert "relationships" in body
    assert "metadata" in body
