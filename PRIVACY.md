# Privacy Policy

## Data Handling

This service stores uploaded document content and extracted facts in its SQLite database.

Persisted data can include:

- original filenames
- raw parsed document text until extraction completes
- extracted truths, entities, and relationships
- tenant metadata (`org_id`, scope, owner user for conversation-scoped docs)

## Isolation Model

- Data is partitioned by `org_id`
- Conversation-scoped data is restricted to the owning user
- Organization-scoped data is readable within the org and writable only with explicit org-write authorization
- Exports are filtered to the caller's visible data set

## Telemetry

This repository does not intentionally add external analytics or tracking. Host applications and surrounding platform services may have their own logging and audit behavior.

## Operational Note

Because this service processes customer documents, deployments should be treated as customer-data systems for retention, backup, and access-control policy.
