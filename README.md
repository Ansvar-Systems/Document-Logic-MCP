# Document-Logic MCP

MCP server for structured document intelligence extraction. Replaces traditional RAG with precise extraction of truths, entities, and relationships - with full citations.

## Purpose

Extract structured knowledge from security assessment documents:
- **Truths** - factual statements with exact citations
- **Entities** - systems, technologies, people, organizations
- **Relationships** - how entities relate (stores, integrates_with, etc.)
- **Entity aliases** - potential name variants with confidence scores

Built for accuracy-critical security workflows: threat modeling, third-party risk, compliance mapping.

## Architecture

**Layer 1: Document Parsing** (deterministic)
- PDF (pdfplumber), DOCX (python-docx), OCR (tesseract)
- Fast (seconds), preserves structure

**Layer 2: Semantic Extraction** (hierarchical LLM)
1. Overview pass: entities, topics, purpose
2. Section pass: truths, relationships with context
3. Cross-reference pass: link references

**Storage:** SQLite + vectors, ephemeral by design

**Query:** Natural language → structured results (broad matching)

## Installation

```bash
pip install -e ".[dev]"
```

Or use Docker:

```bash
docker build -t document-logic-mcp .
docker run -v $(pwd)/data:/app/data document-logic-mcp
```

## Usage

### MCP Tools

**parse_document** - Fast parsing (seconds)
```json
{
  "file_path": "/path/to/document.pdf"
}
```

**extract_document** - LLM extraction (minutes, blocks)
```json
{
  "doc_id": "uuid-from-parse"
}
```

**query_documents** - Natural language query
```json
{
  "query": "What encryption methods are used?"
}
```

**get_entity_aliases** - Entity resolution
```json
{
  "entity_name": "customer_database"
}
```

**export_assessment** - Export deliverable
```json
{
  "format": "json|sqlite|markdown",
  "output_path": "/path/to/export.json"
}
```

### Workflow Example

```python
# 1. Parse documents
doc1 = await parse_document("architecture.pdf")
doc2 = await parse_document("security-policy.docx")

# 2. Extract knowledge (blocks, honest wait)
await extract_document(doc1["doc_id"])
await extract_document(doc2["doc_id"])

# 3. Query
results = await query_documents("customer data encryption")

# 4. Export for client
await export_assessment(format="json", output_path="./deliverable.json")
```

## Design Principles

- **Store precisely, return broadly, let agents reason**
- No premature entity merging (wrong merges corrupt security context)
- No conflict labeling (provide metadata, agent decides)
- Synchronous operations (honest blocking, no hidden state)
- Ephemeral by design (VM isolation, provable deletion)

## Export Formats

**JSON** - Machine-readable, client integrations
**SQLite** - Full database, technical teams can query
**Markdown** - Human-readable report, executives

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=src/document_logic_mcp

# Format code
black src/ tests/
ruff check src/ tests/
```

## License

MIT
