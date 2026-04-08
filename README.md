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

### Docker (Recommended)

```bash
# Build the image
docker build -t document-logic-mcp .

# Run with LLM Gateway (recommended - supports Ollama, Anthropic, OpenAI, etc.)
docker run -d \
  -p 3000:3000 \
  -e LLM_GATEWAY_URL=http://llm-gateway:8001 \
  -e EXTRACTION_MODEL=llama3.1 \
  -v $(pwd)/data:/app/data \
  document-logic-mcp

# OR run with direct Anthropic API (legacy)
docker run -d \
  -p 3000:3000 \
  -e ANTHROPIC_API_KEY=your_key_here \
  -v $(pwd)/data:/app/data \
  document-logic-mcp
```

### Local Development

```bash
pip install -e ".[dev]"

# Set environment variables
export LLM_GATEWAY_URL=http://localhost:8001
export EXTRACTION_MODEL=llama3.1

# Run HTTP server
python -m document_logic_mcp.http_server
```

## Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `PORT` | HTTP server port | `3000` | No |
| `DB_PATH` | SQLite database path | `data/assessment.db` | No |
| **LLM Configuration (Gateway Mode - Recommended)** |
| `LLM_GATEWAY_URL` | LLM Gateway base URL | - | Yes (gateway mode) |
| `LLM_GATEWAY_API_KEY` | Gateway API key | `dev` | No |
| `EXTRACTION_MODEL` | Model for extraction | `claude-sonnet-4-20250514` | No |
| **LLM Configuration (Direct API Mode - Legacy)** |
| `ANTHROPIC_API_KEY` | Anthropic API key | - | Yes (direct mode) |

### LLM Backend Modes

**Gateway Mode (Recommended)** - Uses an LLM Gateway that supports:
- **Ollama** (local models: `llama3.1`, `qwen2.5-coder`, etc.)
- Anthropic (Claude)
- OpenAI (GPT-4)
- Azure AI Foundry
- Google Gemini

**Direct API Mode (Legacy)** - Calls Anthropic API directly. Only supports Claude models.

## Usage

### HTTP API (Content-Based)

The HTTP server provides REST endpoints that accept file content directly (no filesystem access needed).

**POST /parse-content** - Parse document structure (fast, deterministic)
```bash
curl -X POST http://localhost:3000/parse-content \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "document.docx",
    "content": "base64_encoded_file_content"
  }'
```

**POST /extract** - Extract truths/entities/relationships (LLM-based, slow)
```bash
curl -X POST http://localhost:3000/extract \
  -H "Content-Type: application/json" \
  -d '{"doc_id": "uuid_from_parse"}'
```

**GET /documents** - List all documents with status and counts
```bash
curl http://localhost:3000/documents
```

**GET /documents/{doc_id}** - Get full document details with extracted data
```bash
curl http://localhost:3000/documents/uuid_from_parse
```

**POST /query-documents** - Query extracted truths (optionally scoped by doc_ids)
```bash
curl -X POST http://localhost:3000/query-documents \
  -H "Content-Type: application/json" \
  -d '{"query": "encryption methods", "doc_ids": ["uuid1", "uuid2"]}'
```

**GET /health** - Health check
```bash
curl http://localhost:3000/health
```

### MCP Tools (Legacy STDIO Mode)

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

**list_documents** - Discover documents and check status
```json
{}
```

**get_document** - Get full document details with extracted data
```json
{
  "doc_id": "uuid-from-parse-or-list"
}
```

**query_documents** - Natural language query (optionally scoped)
```json
{
  "query": "What encryption methods are used?",
  "doc_ids": ["uuid1"]
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

# 3. Discover what's available (or resume a previous session)
docs = await list_documents()

# 4. Check extraction results for a specific document
detail = await get_document(doc1["doc_id"])

# 5. Query across all or specific documents
results = await query_documents("customer data encryption")
scoped = await query_documents("encryption", doc_ids=[doc1["doc_id"]])

# 6. Export for client
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

## Integration with Ansvar Platform

Document-Logic MCP integrates with the Ansvar TPRM workflow platform to provide structured document intelligence for vendor risk assessments.

### Architecture

```
Ansvar TPRM Workflow
    ↓
Document Classifier Step (use_document_logic_mcp: true)
    ↓
Workflow Input Builder
    ↓
Document-Logic MCP HTTP API
    ├─ Parse: Extract sections (< 1s)
    └─ Extract: LLM-based extraction (1-3 min)
    ↓
Structured JSON → TPRM Agent
    ↓
Risk Analysis with Citations
```

### Configuration in Ansvar

**docker-compose.mcp.yml:**
```yaml
document-logic-mcp:
  image: document-logic-mcp:latest
  environment:
    LLM_GATEWAY_URL: "http://llm-gateway-fastapi:8001"
    EXTRACTION_MODEL: "llama3.1"  # Use local Ollama
  networks:
    - ansvar-network
```

**Workflow Step (TPRM Document Classifier):**
```json
{
  "parameters": {
    "use_original_document": true,
    "use_document_logic_mcp": true
  }
}
```

### Benefits for TPRM

1. **Structured Data** - Agents receive truths/entities, not raw text
2. **Citation Tracking** - Every fact has page/section reference
3. **Local Processing** - Use Ollama (no API costs, data privacy)
4. **Audit Trail** - Extraction results stored with workflow run

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

## Troubleshooting

### "Authentication method not resolved"
Set either `LLM_GATEWAY_URL` + `EXTRACTION_MODEL` or `ANTHROPIC_API_KEY`.

### "Unsupported file type"
Only `.pdf`, `.docx`, and `.json` files are supported. Ensure correct extension.

### Extract takes too long
Use local Ollama models for faster extraction (no rate limits, network latency).

## License

Apache 2.0
