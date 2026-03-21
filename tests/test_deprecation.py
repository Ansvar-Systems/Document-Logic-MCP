"""Tests for LEGACY_ENDPOINTS_ENABLED deprecation flag.

When LEGACY_ENDPOINTS_ENABLED=false, each deprecated endpoint must return HTTP 410.
The new /extract-stateless endpoint must remain unaffected.
"""

import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport


# Patch the module-level flag so the app sees it disabled.
# We import the app after patching to ensure the flag is read correctly,
# but since the app object is already constructed at import time, we patch
# the flag value used inside each handler directly.

@pytest.fixture
async def legacy_disabled_client():
    """HTTP client with LEGACY_ENDPOINTS_ENABLED patched to False."""
    import document_logic_mcp.http_server as hs
    from document_logic_mcp.http_server import app

    with patch.object(hs, "LEGACY_ENDPOINTS_ENABLED", False):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.mark.asyncio
async def test_extract_returns_410_when_disabled(legacy_disabled_client):
    """POST /extract returns 410 when legacy endpoints are disabled."""
    response = await legacy_disabled_client.post(
        "/extract", json={"doc_id": "test-id"}
    )
    assert response.status_code == 410
    assert "deprecated" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_extract_async_returns_410_when_disabled(legacy_disabled_client):
    """POST /extract-async returns 410 when legacy endpoints are disabled."""
    response = await legacy_disabled_client.post(
        "/extract-async", json={"doc_id": "test-id"}
    )
    assert response.status_code == 410
    assert "deprecated" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_documents_returns_410_when_disabled(legacy_disabled_client):
    """GET /documents returns 410 when legacy endpoints are disabled."""
    response = await legacy_disabled_client.get("/documents")
    assert response.status_code == 410
    assert "deprecated" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_document_returns_410_when_disabled(legacy_disabled_client):
    """GET /documents/{doc_id} returns 410 when legacy endpoints are disabled."""
    response = await legacy_disabled_client.get("/documents/some-doc-id")
    assert response.status_code == 410
    assert "deprecated" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_document_returns_410_when_disabled(legacy_disabled_client):
    """DELETE /documents/{doc_id} returns 410 when legacy endpoints are disabled."""
    response = await legacy_disabled_client.delete("/documents/some-doc-id")
    assert response.status_code == 410
    assert "deprecated" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_query_documents_returns_410_when_disabled(legacy_disabled_client):
    """POST /query-documents returns 410 when legacy endpoints are disabled."""
    response = await legacy_disabled_client.post(
        "/query-documents", json={"query": "encryption methods"}
    )
    assert response.status_code == 410
    assert "deprecated" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_entity_aliases_returns_410_when_disabled(legacy_disabled_client):
    """POST /entity-aliases returns 410 when legacy endpoints are disabled."""
    response = await legacy_disabled_client.post(
        "/entity-aliases", json={"entity_name": "PostgreSQL"}
    )
    assert response.status_code == 410
    assert "deprecated" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_export_returns_410_when_disabled(legacy_disabled_client):
    """POST /export returns 410 when legacy endpoints are disabled."""
    response = await legacy_disabled_client.post(
        "/export", json={"format": "json", "output_path": "/tmp/out.json"}
    )
    assert response.status_code == 410
    assert "deprecated" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_stateless_extract_unaffected_by_flag(legacy_disabled_client):
    """POST /extract-stateless is NOT gated by LEGACY_ENDPOINTS_ENABLED.

    The endpoint should not return 410 — it may return 422 (validation error)
    because we send an invalid payload, but NOT 410.
    """
    response = await legacy_disabled_client.post(
        "/extract-stateless", json={"sections": [], "filename": "test.pdf",
                                    "schema_version": "1.0", "input_hash": "abc"}
    )
    assert response.status_code != 410


@pytest.mark.asyncio
async def test_health_unaffected_by_flag(legacy_disabled_client):
    """GET /health is never gated by LEGACY_ENDPOINTS_ENABLED."""
    response = await legacy_disabled_client.get("/health")
    assert response.status_code == 200
