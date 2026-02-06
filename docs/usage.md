# Usage Guide

## Document Processing Workflow

### 1. Parse Documents

Fast (seconds), deterministic extraction of document structure:

```python
result = await parse_document(file_path="/path/to/doc.pdf")
# Returns: {doc_id, filename, sections_count, page_count, status, entities_preview}
```

Supported formats:
- PDF (.pdf)
- Word (.docx)
- JSON (.json) — structured data (e.g., vendor profiles)

### 2. Extract Knowledge

Slow (1-5 minutes), LLM-based hierarchical extraction. **Blocks until complete**:

```python
result = await extract_document(doc_id="uuid-from-parse")
# Returns: {doc_id, status, truths_extracted, entities_found, relationships_found,
#           overview, truths[], entities[], relationships[]}
```

Extraction process:
1. **Pass 1: Overview** — High-level entities, topics, document purpose
2. **Pass 2: Per-section** — Detailed truths, relationships with context
3. **Pass 3: Synthesis** (optional) — Cross-section consolidation, activated by `analysis_context`

#### Domain-Specific Extraction

Use `analysis_context` to activate domain-specific extraction intelligence:

```python
# STRIDE threat modeling: trust boundaries, data flows, implicit negatives, ambiguity flags
result = await extract_document(
    doc_id="uuid-from-parse",
    analysis_context="stride_threat_modeling"
)

# TPRM vendor assessment: certifications, subprocessors, SLAs, data residency
result = await extract_document(
    doc_id="uuid-from-parse",
    analysis_context="tprm_vendor_assessment"
)
```

When `analysis_context` is set, the response includes a `synthesis` key with:
- `component_registry` — deduplicated inventory of systems/services
- `trust_boundaries` — data crossing points between trust domains
- `implicit_negatives` — security topics conspicuously absent
- `ambiguities` — vague security language needing clarification

#### Model Override

Override the extraction model per-call:

```python
result = await extract_document(
    doc_id="uuid-from-parse",
    extraction_model="ollama/llama3.1"  # or "gpt-4o", etc.
)
```

### 3. Discover Documents

List all documents in the database with their extraction status:

```python
result = await list_documents()
# Returns: {documents: [{doc_id, filename, status, upload_date, sections_count,
#           truths_count, entities_count, relationships_count}], count: N}
```

Status values: `parsed` (ready for extraction), `extracting` (in progress), `completed` (done).

### 4. Inspect a Document

Get full details for a single document including all extracted data:

```python
result = await get_document(doc_id="uuid-from-parse-or-list")
# Returns: {doc_id, filename, status, upload_date, sections_count,
#           truths_count, entities_count, relationships_count,
#           truths[], entities[], relationships[]}
```

Use this to check extraction status or retrieve results for downstream processing.

### 5. Query Documents

Natural language query with broad matching:

```python
results = await query_documents(query="encryption methods")
# Returns: {results: [{truth_id, statement, similarity, source, ...}], count: N}
```

Scope queries to specific documents:

```python
results = await query_documents(
    query="encryption methods",
    doc_ids=["uuid-1", "uuid-2"]
)
```

Each result includes:
- Exact statement from document
- Full source citation (document, section, page, paragraph)
- Statement type (assertion/plan/requirement/recommendation)
- Confidence score
- Related entities
- Source authority level

### 6. Entity Resolution

Get potential aliases for entity disambiguation:

```python
result = await get_entity_aliases(entity_name="customer_database")
# Returns: {entity, potential_aliases: [{entity, confidence, evidence}], definitely_not: [...]}
```

Use this when agent needs to understand if "CRM system" and "Salesforce" refer to the same thing.

### 7. Export Assessment

Create deliverable for clients:

```python
# JSON - machine readable
await export_assessment(format="json", output_path="./assessment.json")

# SQLite - full database
await export_assessment(format="sqlite", output_path="./assessment.db")

# Markdown - human readable
await export_assessment(format="markdown", output_path="./report.md")
```

## Query Patterns

### Security Controls
```
query: "authentication mechanisms"
query: "encryption at rest"
query: "access control policies"
```

### Architecture
```
query: "data storage systems"
query: "external integrations"
query: "trust boundaries"
```

### Compliance
```
query: "GDPR data protection"
query: "audit logging"
query: "incident response"
```

## Understanding Results

### Statement Types

**assertion** - Factual statement (present tense)
- "System uses AES-256 encryption"

**plan** - Future intention (future tense)
- "Encryption will be implemented in Q3"

**requirement** - Obligation (modal verbs: must, shall)
- "Data must be encrypted at rest"

**recommendation** - Suggestion (should, could)
- "Consider implementing MFA"

### Confidence Scores

- **0.9-1.0** - Explicit, unambiguous statement
- **0.7-0.9** - Clear statement with minor ambiguity
- **0.5-0.7** - Implied or indirect statement
- **0.0-0.5** - Weak evidence or heavy interpretation

### Source Authority

**high** - Official documentation, policies, architecture docs
**medium** - Guidelines, procedures, standards
**low** - Meeting notes, drafts, informal docs

## Error Handling

All tools return structured JSON errors instead of raw exceptions:

```json
{
  "error": "File not found: /path/to/doc.pdf",
  "error_type": "file_not_found"
}
```

Error types: `file_not_found`, `invalid_input`, `internal_error`

## Tips for Accuracy

1. **Always check source citations** - Every truth has exact source
2. **Compare statement types** - Plans vs assertions reveal implementation gaps
3. **Check document dates** - Newer assertions may supersede older plans
4. **Use entity aliases** - Multiple names for same system are preserved
5. **Review confidence scores** - Lower confidence = needs human verification

## Ephemeral Design

Each assessment is isolated:
- Fresh VM = fresh database
- No versioning, no history
- Delete `/data/assessment.db` = clean slate
- Export deliverable before wiping

Perfect for:
- Client engagements (strict data isolation)
- Air-gapped environments
- Time-limited assessments
