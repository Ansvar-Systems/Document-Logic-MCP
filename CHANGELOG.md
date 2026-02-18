# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **FTS5 full-text search** replacing LIKE-based keyword queries, with automatic LIKE fallback
- FTS5 input sanitization (`_sanitize_fts5_query`) preventing query syntax injection
- Batch entity fetching eliminating N+1 queries in search and document retrieval
- `include_extracted_data` parameter on `get_document` (default `false`) — returns counts only unless requested
- Pagination on `list_documents` (`limit`/`offset`) with total count in response
- `limit` parameter on `query_documents` (1-100, default 20)
- Input validation helper `_require_str()` with max-length bounds on all string params
- `analysis_context` enum validation (rejects unknown context values)
- Export path traversal protection via `ALLOWED_DOC_DIRS`
- `resolve_technology_name` and `suggest_terminology_addition` tools on STDIO transport (transport parity)
- Enhanced tool descriptions with purpose, edge cases, chaining hints, and "when NOT to use"
- FTS5 virtual table with INSERT/DELETE/UPDATE sync triggers
- Database indexes on `relationships.doc_id`, `truth_entities.truth_id`, `truth_entities.entity_id`
- `DELETE` journal mode (Docker/serverless compatible) and `PRAGMA foreign_keys = ON`
- `document_metadata` column on `documents` table for parser-extracted metadata
- `/health` endpoint with DB connectivity check, document count, and version info
- CI workflow (`.github/workflows/ci.yml`): tests on Python 3.11+3.12, lint, type check, Docker build
- Security scanning workflow (`.github/workflows/security-scanning.yml`): CodeQL, Semgrep, Trivy, Gitleaks, Socket, OSSF Scorecard
- `server.json` MCP registry metadata
- Populated `manifest.json` tools array
- Dockerfile `HEALTHCHECK` directive
- Test suite: FTS5 sanitization (6 tests), FTS5 search integration (3), file validation (5), pagination (2)

### Fixed
- MCP error responses now set `isError: true` (protocol compliance) with `CallToolResult`
- Error JSON key renamed from `error_type` to `type` for consistency
- Error handler now catches `KeyError` and `TypeError` as `invalid_input` (not just `ValueError`)
- `cryptography` bumped to >=46.0.5 (CVE-2026-26007)
- `Pillow` bumped to >=12.1.1 (CVE-2026-25990)
- Dockerfile installs production dependencies only (`pip install -e .` not `.[dev]`)

### Security
- All FTS5 queries use parameterized placeholders — no f-string SQL injection vectors
- FTS5 special character stripping prevents MATCH syntax injection
- Export output path validated against `ALLOWED_DOC_DIRS`
- 6-layer automated security scanning in CI
