# Document-Logic MCP

Structured document parsing, extraction, and truth querying for the Ansvar platform.

This service is not a public reference server. It stores uploaded customer documents and must be treated as a tenant-scoped internal component.

## What It Does

- Parse documents into sections
- Extract truths, entities, and relationships with citations
- Query extracted truths by natural language
- Export only the documents visible to the caller

Supported document scopes:

- `conversation`: visible only to the owning user within the org
- `organization`: visible across the org, but write operations require explicit org-write authorization

## Security Model

HTTP mode requires:

- `X-API-Key` unless `MCP_AUTH_DISABLED=true`
- `X-Org-Id` on every authenticated request
- `X-User-Id` for conversation-scoped access
- `X-Allow-Org-Write: true` for organization-scoped writes

Tenant isolation is enforced in:

- document create/list/get/query/delete
- extraction start and status lookup
- export output

Health checks remain unauthenticated at `GET /health`.

## Configuration

| Variable | Description | Default |
| --- | --- | --- |
| `PORT` | HTTP server port | `3000` |
| `DB_PATH` | SQLite database path | `data/assessment.db` |
| `MCP_API_KEY` | Shared service auth key for HTTP mode | unset |
| `MCP_AUTH_DISABLED` | Disable HTTP auth for local/dev only | `false` |
| `MAX_FILE_SIZE_MB` | Max upload size | `50` |
| `ALLOWED_DOC_DIRS` | Colon-separated allowlist for filesystem parsing | unset |
| `LLM_GATEWAY_URL` | LLM gateway base URL | unset |
| `LLM_GATEWAY_API_KEY` | LLM gateway API key | unset |
| `EXTRACTION_MODEL` | Extraction model | `claude-sonnet-4-20250514` |
| `ANTHROPIC_API_KEY` | Direct Anthropic fallback | unset |

## HTTP Usage

Parse uploaded content:

```bash
curl -X POST http://localhost:3000/parse-content \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MCP_API_KEY" \
  -H "X-Org-Id: org-123" \
  -H "X-User-Id: user-456" \
  -d '{
    "filename": "architecture.pdf",
    "content": "base64_encoded_file_content",
    "scope": "conversation"
  }'
```

Start extraction:

```bash
curl -X POST http://localhost:3000/extract-async \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MCP_API_KEY" \
  -H "X-Org-Id: org-123" \
  -H "X-User-Id: user-456" \
  -d '{"doc_id": "uuid-from-parse"}'
```

List accessible documents:

```bash
curl http://localhost:3000/documents \
  -H "X-API-Key: $MCP_API_KEY" \
  -H "X-Org-Id: org-123" \
  -H "X-User-Id: user-456"
```

Query truths:

```bash
curl -X POST http://localhost:3000/query-documents \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MCP_API_KEY" \
  -H "X-Org-Id: org-123" \
  -H "X-User-Id: user-456" \
  -d '{"query": "encryption methods", "doc_ids": ["uuid1"]}'
```

## STDIO MCP Usage

The legacy STDIO tools now require explicit tenant context on all document-bearing operations.

Example:

```json
{
  "name": "parse_document",
  "arguments": {
    "file_path": "/tmp/architecture.pdf",
    "org_id": "org-123",
    "scope": "conversation",
    "owner_user_id": "user-456"
  }
}
```

Organization-scoped writes must also pass:

```json
{
  "allow_org_write": true
}
```

## Development

```bash
pip install -e ".[dev]"
pytest
python -m document_logic_mcp.http_server
```

## Notes

- `export_assessment` no longer copies the raw backing database wholesale; it emits a filtered view of the caller's accessible documents.
- Conversation-scoped documents require an owning user at creation time.
- Do not expose this service directly to untrusted networks.
