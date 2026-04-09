# Privacy Policy

## Data Collection

**This MCP server does not log or persist customer document content.**

- Customer documents are processed in-memory and not written to persistent storage
- No telemetry, tracking, or analytics are collected
- No cookies or session data
- Structured results (truths, entities, relationships) may be written to an ephemeral SQLite database when using stateful legacy endpoints; this database is local and not transmitted externally
- LLM API calls are made at runtime to an external LLM gateway for document extraction

## Architecture

This MCP server is a **stateless document extraction utility**. Documents are accepted as input, processed through a structured extraction pipeline using an LLM, and results are returned to the caller. In stateless mode (`/extract-stateless`), no data is written to disk.

The server is written in Python and communicates with an external LLM gateway (configured via `GATEWAY_URL` / `LITELLM_BASE_URL` environment variables). Customer documents are forwarded to the LLM for extraction and are subject to that gateway's data-handling policies.

## Data Processed

When you submit a document:

1. The document content is forwarded to the configured LLM gateway for structured extraction
2. The LLM gateway processes the document and returns structured facts (truths, entities, relationships)
3. In stateless mode, results are returned in the HTTP response and nothing is written to disk
4. In stateful (legacy) mode, results may be persisted to a local SQLite database at `DB_PATH`

The LLM gateway operator's privacy policy governs how document content is handled during inference.

## Host Environment

When this MCP server runs inside a host application (Claude Desktop, Cursor, VS Code, etc.), the **host application's** privacy policy governs how your interactions are processed. This MCP server itself has no visibility into or control over the host's data practices.

## Authentication

When `MCP_API_KEY` is set, all endpoints (except `/health`) require a valid API key. Without it, the server operates in unauthenticated development mode.

## Contact

For privacy questions about this MCP server: [Ansvar Systems](https://ansvar.eu)
