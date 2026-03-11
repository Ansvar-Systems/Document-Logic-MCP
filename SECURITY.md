# Security Policy

## Supported Versions

| Version | Supported |
| --- | --- |
| 1.x | Yes |

## Reporting a Vulnerability

1. Do not open a public issue.
2. Email `security@ansvar.eu`.
3. Include impact, reproduction steps, and affected deployment path.

## Security Architecture

This service processes uploaded customer documents. It is not public reference data.

Current controls:

- HTTP authentication with `X-API-Key` unless explicitly disabled for local development
- Required tenant headers (`X-Org-Id`, `X-User-Id` where applicable)
- Conversation-vs-organization scope enforcement on reads and writes
- Explicit `X-Allow-Org-Write` gate for organization-scoped mutations
- Parameterized SQL throughout
- File-size and allowed-directory validation on parse paths
- Filtered exports instead of raw database copies

Operational requirements:

- Bind the service to trusted internal networks only
- Rotate `MCP_API_KEY` like any other service credential
- Do not run `MCP_AUTH_DISABLED=true` outside local development
- Treat the SQLite database as customer data at rest
