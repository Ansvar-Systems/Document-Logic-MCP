# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in this MCP server, please report it responsibly:

1. **Do NOT open a public issue**
2. Email: security@ansvar.eu
3. Include: description, reproduction steps, potential impact

We aim to acknowledge reports within 48 hours and provide a fix within 7 days for critical issues.

## Security Architecture

- **Authentication**: All endpoints (except `/health`) are protected by `MCP_API_KEY` when set. Without the key configured, the server operates in unauthenticated development mode — do not expose to untrusted networks without setting this variable.
- **LLM credentials required**: The server makes outbound LLM API calls. Credentials (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or gateway credentials) must be configured in the environment.
- **Network calls at runtime**: Outbound HTTPS calls are made to the configured LLM gateway for each extraction request. The gateway URL is configurable via `GATEWAY_URL` / `LITELLM_BASE_URL`.
- **Ephemeral SQLite writes**: In stateful (legacy) mode, the server writes extracted data to a local SQLite database at `DB_PATH`. In stateless mode (`/extract-stateless`), no disk writes occur.
- **Path traversal prevention**: The `/parse-file` endpoint validates that resolved paths remain within `SHARED_FILES_PATH`.
- **Input validation**: All inputs validated via Pydantic models before processing.
- **Body size and section count caps**: Configurable via `EXTRACT_MAX_BODY_BYTES` and `EXTRACT_MAX_SECTIONS` to prevent resource exhaustion.
- **No customer data logged**: Request/response bodies containing customer document content are not logged.

## Dependencies

Dependencies are monitored via GitHub Dependabot and updated regularly. Security scanning is enabled via GitHub Advanced Security (CodeQL + secret scanning).
