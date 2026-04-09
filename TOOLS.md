# Tools — Document Logic MCP

HTTP API reference for the Document Logic MCP server. All endpoints (except `/health`) require
`X-API-Key` header when `MCP_API_KEY` is configured.

Base URL: `http://localhost:3000` (default)

---

## Meta / Discovery

### `GET /about`

Returns server metadata: name, version, capabilities, and runtime information.

**Response**
```json
{
  "server": "document-logic-mcp",
  "version": "0.1.0",
  "description": "Structured document intelligence extraction with citations",
  "runtime": "Python",
  "capabilities": ["parse", "extract", "resolve-technology-name", "suggest-terminology-addition"],
  "stateless_mode": true,
  "_meta": { "disclaimer": "...", "source": "document-logic-mcp", "version": "0.1.0" }
}
```

### `GET /list-sources`

Lists data sources used by this server. This is a stateless extraction utility — it has no
static corpus. The only persistent resource is the technology terminology JSON.

**Response**
```json
{
  "sources": [...],
  "note": "...",
  "_meta": { "disclaimer": "...", "source": "document-logic-mcp", "version": "0.1.0" }
}
```

### `GET /check-data-freshness`

Reports freshness of the technology terminology resource and the server version.

**Response**
```json
{
  "terminology_resource": { "last_modified": "...", "entry_count": 102, "status": "ok" },
  "server_version": "0.1.0",
  "_meta": { "disclaimer": "...", "source": "document-logic-mcp", "version": "0.1.0" }
}
```

### `GET /health`

Unauthenticated health check (no API key required). Returns server status and optional DB stats
when a legacy database is configured.

**Response**
```json
{
  "server": "document-logic-mcp",
  "version": "0.1.0",
  "db_status": "not_configured",
  "status": "ok"
}
```

---

## Core Extraction (Stateless)

### `POST /extract-stateless`

**Primary endpoint.** Accepts pre-parsed sections, runs LLM extraction, and returns structured
results. No database writes — all processing is in-memory.

Supports optional streaming via `?stream_progress=true` (NDJSON).

**Request**
```json
{
  "sections": [
    {
      "section_ref": "1.1",
      "title": "Introduction",
      "content": "...",
      "section_index": 0,
      "page_start": 1,
      "page_end": 2,
      "parent_ref": null
    }
  ],
  "filename": "document.pdf",
  "analysis_context": "stride_threat_modeling",
  "extraction_model": null,
  "schema_version": "1.0",
  "input_hash": "sha256:...",
  "org_id": null
}
```

`analysis_context` options: `stride_threat_modeling`, `tprm_vendor_assessment`, `compliance_mapping`

**Response**
```json
{
  "truths": [...],
  "entities": [...],
  "relationships": [...],
  "overview": {...},
  "synthesis": {...},
  "metadata": {...}
}
```

Response header: `X-Extraction-Schema-Version: <schema_version>`

**Streaming** (`?stream_progress=true`): Returns `application/x-ndjson`. Each completed section
emits a progress JSON line. Final line has `"event": "complete"` with the full result.

---

## Parsing

### `POST /parse-content`

Parse a document from base64-encoded content. No filesystem access required.

**Request**
```json
{
  "filename": "document.pdf",
  "content": "<base64-encoded file bytes>"
}
```

**Response**: Parsed document structure with sections.

### `POST /parse-file`

Parse a document from the shared filesystem by object key (resolves within `SHARED_FILES_PATH`).

**Request**
```json
{
  "object_key": "{file_id}/{filename}",
  "filename": "original-name.pdf"
}
```

**Response**: Parsed document structure with sections.

---

## Terminology

### `POST /resolve-technology-name`

Deterministic normalization of a raw technology string using the technology terminology resource.

**Request**
```json
{
  "raw_name": "ELK Stack"
}
```

**Response**
```json
{
  "canonical_name": "Elastic Stack",
  "version": null,
  "match_method": "exact",
  "confidence": 1.0
}
```

Returns `null` `canonical_name` when no match or result is ambiguous.

### `POST /suggest-terminology-addition`

Queue a terminology addition suggestion for human review. Called when an agent resolves a
technology name not in the terminology table. Does **not** auto-add to the table.

**Request**
```json
{
  "raw_string": "Splunk ES",
  "resolved_canonical": "Splunk Enterprise Security",
  "context": "...snippet from source document..."
}
```

---

## Legacy Endpoints (Stateful)

The following endpoints require a configured `DB_PATH` SQLite database. They are disabled when
`LEGACY_ENDPOINTS_ENABLED=false` and return HTTP 410 in that case.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/parse` | Parse a document from a local file path |
| `POST` | `/extract` | Extract truths/entities from a parsed document |
| `POST` | `/extract-async` | Start extraction as a background task (returns 202) |
| `GET`  | `/documents` | List documents with extraction status |
| `GET`  | `/documents/{doc_id}` | Get document details |
| `DELETE` | `/documents/{doc_id}` | Delete a document and its extracted data |
| `POST` | `/query-documents` | Natural language query over extracted truths |
| `POST` | `/entity-aliases` | Find potential aliases for a named entity |
| `POST` | `/export` | Export extracted data as JSON, SQLite, or Markdown |
