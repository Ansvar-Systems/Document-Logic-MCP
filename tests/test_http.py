import base64
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Must set env before importing the app.
os.environ["DB_PATH"] = "/tmp/test-document-logic-http.db"
os.environ["MCP_API_KEY"] = "test-mcp-key"

from document_logic_mcp.database import Database
from document_logic_mcp.http_server import app


@pytest.fixture
def client():
    db_path = Path("/tmp/test-document-logic-http.db")
    if db_path.exists():
        db_path.unlink()
    with TestClient(app) as test_client:
        yield test_client
    if db_path.exists():
        db_path.unlink()


def _headers(*, org_id: str = "org-1", user_id: str | None = "user-1", allow_org_write: bool = False) -> dict[str, str]:
    headers = {
        "X-API-Key": "test-mcp-key",
        "X-Org-Id": org_id,
    }
    if user_id:
        headers["X-User-Id"] = user_id
    if allow_org_write:
        headers["X-Allow-Org-Write"] = "true"
    return headers


def _parse_content(
    client,
    *,
    filename: str,
    content: str,
    scope: str = "conversation",
    org_id: str = "org-1",
    user_id: str | None = "user-1",
    allow_org_write: bool = False,
):
    encoded = base64.b64encode(content.encode()).decode()
    return client.post(
        "/parse-content",
        json={"filename": filename, "content": encoded, "scope": scope},
        headers=_headers(org_id=org_id, user_id=user_id, allow_org_write=allow_org_write),
    )


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "degraded"}


def test_http_requires_api_key(client):
    response = client.get("/documents", headers={"X-Org-Id": "org-1"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_http_visibility_is_scoped_by_org_and_owner(client):
    own = _parse_content(client, filename="own.txt", content="Own conversation doc.")
    assert own.status_code == 200
    own_doc_id = own.json()["doc_id"]

    other = _parse_content(
        client,
        filename="other.txt",
        content="Other conversation doc.",
        org_id="org-1",
        user_id="user-2",
    )
    assert other.status_code == 200

    org_doc = _parse_content(
        client,
        filename="policy.txt",
        content="Organization policy doc.",
        scope="organization",
        org_id="org-1",
        user_id="admin-1",
        allow_org_write=True,
    )
    assert org_doc.status_code == 200

    foreign = _parse_content(
        client,
        filename="foreign.txt",
        content="Foreign org doc.",
        org_id="org-2",
        user_id="user-9",
    )
    assert foreign.status_code == 200

    listing = client.get("/documents", headers=_headers(org_id="org-1", user_id="user-1"))
    assert listing.status_code == 200
    assert listing.json()["total"] == 2

    own_doc = client.get(f"/documents/{own_doc_id}", headers=_headers(org_id="org-1", user_id="user-1"))
    assert own_doc.status_code == 200

    forbidden = client.get(
        f"/documents/{other.json()['doc_id']}",
        headers=_headers(org_id="org-1", user_id="user-1"),
    )
    assert forbidden.status_code == 404

    foreign_hidden = client.get(
        f"/documents/{foreign.json()['doc_id']}",
        headers=_headers(org_id="org-1", user_id="user-1"),
    )
    assert foreign_hidden.status_code == 404


def test_http_org_writes_require_explicit_header(client):
    create = _parse_content(
        client,
        filename="org.txt",
        content="Organization document.",
        scope="organization",
        org_id="org-1",
        user_id="user-1",
    )
    assert create.status_code == 403


def test_http_conversation_scope_requires_user_header(client):
    create = _parse_content(
        client,
        filename="conversation.txt",
        content="Conversation document.",
        scope="conversation",
        org_id="org-1",
        user_id=None,
    )
    assert create.status_code == 400
    assert "X-User-Id" in create.json()["detail"]


@pytest.mark.asyncio
async def test_http_query_only_returns_accessible_truths(client):
    db = Database("/tmp/test-document-logic-http.db")
    await db.initialize()
    async with db.connection() as conn:
        for doc_id, org_id, owner_user_id, scope, filename in (
            ("doc-own", "org-1", "user-1", "conversation", "own.txt"),
            ("doc-other", "org-1", "user-2", "conversation", "other.txt"),
            ("doc-org", "org-1", None, "organization", "policy.txt"),
        ):
            await conn.execute(
                """
                INSERT INTO documents (
                    doc_id, org_id, owner_user_id, scope, filename, upload_date, sections_count, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (doc_id, org_id, owner_user_id, scope, filename, "2026-03-11T00:00:00", 1, "completed"),
            )
        for truth_id, doc_id, statement in (
            ("truth-own", "doc-own", "Own document mentions encryption"),
            ("truth-other", "doc-other", "Other document mentions encryption"),
            ("truth-org", "doc-org", "Organization policy requires MFA"),
        ):
            await conn.execute(
                """
                INSERT INTO truths (
                    truth_id, doc_id, statement, source_section,
                    source_page, statement_type, confidence, source_authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (truth_id, doc_id, statement, "Security", 1, "assertion", 0.9, "high"),
            )
        await conn.commit()

    response = client.post(
        "/query-documents",
        json={"query": "encryption MFA"},
        headers=_headers(org_id="org-1", user_id="user-1"),
    )
    assert response.status_code == 200
    statements = {result["statement"] for result in response.json()["results"]}
    assert "Own document mentions encryption" in statements
    assert "Organization policy requires MFA" in statements
    assert "Other document mentions encryption" not in statements
