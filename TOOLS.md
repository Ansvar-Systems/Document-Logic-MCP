# Tools - Document Logic MCP

All document-bearing tools are tenant-scoped.

Required arguments by tool:

- `parse_document`: `file_path`, `org_id`, `scope`, and `owner_user_id` when `scope=conversation`
- `extract_document`: `doc_id`, `org_id`
- `list_documents`: `org_id`
- `get_document`: `doc_id`, `org_id`
- `delete_document`: `doc_id`, `org_id`
- `query_documents`: `query`, `org_id`
- `get_entity_aliases`: `entity_name`, `org_id`
- `export_assessment`: `format`, `output_path`, `org_id`
- `suggest_terminology_addition`: `raw_string`, `org_id`

Optional access arguments:

- `user_id`: required to access conversation-scoped documents
- `scope`: `conversation` or `organization` on create
- `allow_org_write`: must be `true` for organization-scoped writes

Non-document utility tool:

- `resolve_technology_name`: deterministic terminology normalization, no tenant data access
