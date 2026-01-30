# Document-Logic MCP Design

**Date:** 2026-01-30
**Status:** Approved
**Purpose:** Replace RAG in Ansvar platform with structured document intelligence

---

## Problem Statement

Traditional RAG provides "possibly relevant chunks" but lacks:
- **Provenance** - can't cite exact sources for claims
- **Structured knowledge** - no categorization of truths, assumptions, gaps
- **Conflict detection** - contradictory information silently accepted
- **Temporal awareness** - outdated information mixed with current
- **Entity resolution** - same concepts called different names across documents

For accuracy-critical security assessments (threat modeling, third-party risk, compliance), we need **structured extraction with citations** instead of similarity-based retrieval.

---

## Architecture

### Core Principle
**Store precisely, return broadly, let agents reason.**

The MCP doesn't make judgments about conflicts, gaps, or relevance - it extracts everything accurately and provides rich metadata for downstream agents to reason about.

### Responsibilities

**Document-Logic-MCP does:**
- Parse documents (deterministic)
- Extract truths, entities, relationships (LLM-based)
- Store structured knowledge (SQLite + vectors)
- Query with natural language (return structured results)
- Export deliverables (JSON/SQLite/Markdown)

**Document-Logic-MCP does NOT:**
- Choose which LLM to use (platform provides)
- Know framework/regulation requirements (other MCPs provide)
- Detect gaps (workflow agents compare against requirements)
- Merge entities prematurely (stores variants with alias hints)

---

## Data Model

### Truths
Each truth extracted from documents includes:
```json
{
  "statement": "Customer data encrypted at rest using AES-256",
  "source": {
    "document": "architecture-v2.pdf",
    "section": "4.2",
    "page": 12,
    "paragraph": 3
  },
  "document_date": "2024-03-15",
  "statement_type": "assertion",  // assertion, plan, requirement, recommendation
  "confidence": 0.95,
  "related_entities": ["customer_data", "AES-256", "encryption"],
  "source_authority": "high"  // official doc vs meeting notes
}
```

### Entities
Entities are stored exactly as they appear in source documents:
```json
{
  "entity": "customer_database",
  "document": "architecture-v2.pdf",
  "mentions": [
    {"section": "4.1", "page": 10, "context": "..."}
  ],
  "potential_aliases": [
    {
      "entity": "Salesforce",
      "confidence": 0.7,
      "evidence": "co-occur in same paragraph, doc A section 4"
    },
    {
      "entity": "CRM_system",
      "confidence": 0.9,
      "evidence": "explicitly equated in doc B page 3"
    }
  ],
  "definitely_not": [
    {
      "entity": "product_database",
      "evidence": "doc C explicitly distinguishes these"
    }
  ]
}
```

**Rationale:** Wrong merges are worse than no merges in security contexts. "Vendor's system" vs "our integration with vendor" vs "vendor data we store" have different threat profiles - premature merging corrupts the knowledge base.

### Relationships
```json
{
  "entity_a": "customer_database",
  "relationship_type": "stores",
  "entity_b": "customer_data",
  "source": "architecture-v2.pdf, page 10",
  "confidence": 0.9
}
```

### No Conflict Labels
The MCP does NOT label conflicts. Instead, it groups related truths together with rich metadata:

```json
// Query: "customer data encryption"
{
  "truths_about": ["customer_data", "encryption"],
  "results": [
    {
      "statement": "Customer data encrypted at rest using AES-256",
      "source": "architecture-v2.pdf, page 12",
      "document_date": "2024-03-15",
      "statement_type": "assertion"
    },
    {
      "statement": "Data at rest encryption planned for Q3 2023",
      "source": "security-roadmap.pptx, slide 8",
      "document_date": "2023-01-10",
      "statement_type": "plan"
    },
    {
      "statement": "Encryption not yet implemented for legacy database",
      "source": "audit-findings.docx, finding 4.2",
      "document_date": "2024-06-01",
      "statement_type": "assertion"
    }
  ]
}
```

The agent sees all three, reasons about timeline and statement types, identifies the tension.

---

## Extraction Pipeline

### Layer 1: Document Parsing (Deterministic)
- **Libraries:** pdfplumber (tables), python-docx (structure), tesseract (OCR)
- **Output:** Structured text, sections, metadata, document hierarchy
- **Speed:** Seconds
- **Critical:** Most extraction projects fail here (GIGO)

### Layer 2: Semantic Extraction (Hierarchical LLM)

**Pass 1 - Document Overview:**
- Input: Full document or large sections
- Output: High-level entities, topics, document purpose
- Creates skeleton for contextualized extraction

**Pass 2 - Section Extraction:**
- Input: Each section + context from Pass 1
- Prompt: "This section is about [authentication] in a document about [system X architecture]. Extract truths."
- Output: Truths, entities, statement types, relationships

**Pass 3 - Cross-Reference Resolution:**
- Input: Full document with extracted truths
- Prompt: "Section 3 says 'encryption per policy.' Section 7 defines the encryption policy. Link them."
- Output: Resolved references, linked entities

**Rationale:**
- Not embedding-based chunking (splits context - "encryption per Appendix B" meaningless without Appendix B)
- Not NLP+LLM hybrid (traditional NER fails on "NIBE Fighter 1215", "DORA Article 6")
- Hierarchical LLM preserves document-level context
- Extraction happens ONCE per document, cost negligible for accuracy-critical work

---

## MCP Interface

### Tools (Synchronous)

**parse_document(file_path) → {doc_id, sections, metadata, entities_found}**
- Fast (seconds), deterministic
- Returns document structure immediately
- Idempotent - re-upload same doc = new doc_id

**extract_document(doc_id) → {truths, entities, relationships, alias_graph}**
- Slow (minutes), BLOCKS
- Honest - agent knows it's waiting, can log progress
- No hidden state, no polling loops

**query_documents(natural_language_query) → [truths with metadata]**
- Fast
- Broad semantic matching internally
- Returns structured results with full provenance
- Agent filters/reasons about results

**export_assessment(format) → file_path**
- Formats: "json", "sqlite", "markdown"
- JSON: machine-readable for client integrations
- SQLite: full database for technical teams
- Markdown: human-readable report for executives

### Resources

**documents://{doc_id}** - Access extracted truths and entities
**documents://{doc_id}/entities** - Entity graph with aliases
**documents://{doc_id}/raw** - Original parsed text

---

## Query Model

**Input:** Natural language query
**Internal:** Broad semantic retrieval (embeddings + metadata filtering)
**Output:** Structured truths with full metadata

**Principle:** Return MORE rather than being clever. Agent is an LLM - it can filter. What it can't do is find things the MCP decided weren't relevant.

**Example:**
```
Query: "What do the documents say about encryption?"

Internal: Match "encryption", "AES", "TLS", "data protection", etc.

Return: [
  {truth with full metadata},
  {truth with full metadata},
  ...
]

Agent: Filters and reasons about which truths are relevant
```

---

## Storage

**Backend:** SQLite + sqlite-vss (or ChromaDB)
**Location:** `/data/assessment.db`
**Persistence:** Single file

**Ephemeral by Design:**
- Fresh VM = fresh extraction
- No versioning, no history
- Delete one file = clean slate
- No client data leakage between engagements

**Client benefits:**
- "Where's our data?" → "Isolated VM, destroyed after delivery"
- "Can you prove deletion?" → "VM image reverted to clean snapshot"

---

## Deployment

```
document-logic-mcp/
├── Dockerfile
├── data/
│   └── assessment.db      # SQLite + vectors, ephemeral
├── parsers/               # pdfplumber, python-docx, tesseract
├── extraction/            # Prompts, schema definitions
└── embeddings/            # MiniLM (bundled)
```

**Air-gapped ready:**
- All parsing libraries pure Python
- Embedding model bundled
- LLM calls through platform abstraction
- No external dependencies

---

## Integration with Ansvar Platform

### Workflow Agent Orchestration

```python
# Parse phase (fast)
for doc in uploaded_documents:
    parse_document(doc)

# Extract phase (serial, predictable)
for doc_id in parsed_docs:
    extract_document(doc_id)  # blocks honestly

# Query phase
truths = query_documents("What encryption methods are used?")

# Compare with requirements (from regulation MCPs)
requirements = regulation_mcp.get_requirements("DORA Article 6")
gaps = identify_gaps(truths, requirements)
```

### Gap Detection Pattern

1. **Regulation MCP** provides: "DORA requires ICT risk management processes"
2. **Document-Logic-MCP** provides: Truths about ICT risk management from documents
3. **Workflow Agent** compares and identifies: Evidence, gaps, compliance status

Gap detection happens at orchestration layer, NOT extraction layer.

---

## Export Deliverable

The structured knowledge export is itself a valuable product:

```json
{
  "assessment_id": "uuid",
  "exported_at": "2024-01-30T10:00:00Z",
  "documents": [
    {
      "id": "doc_001",
      "filename": "architecture-v2.pdf",
      "document_date": "2024-03-15",
      "sections": [...]
    }
  ],
  "truths": [
    {
      "statement": "Customer data encrypted using AES-256",
      "source": {"document": "arch-v2.pdf", "section": "4.2", "page": 12},
      "statement_type": "assertion",
      "confidence": 0.95,
      "related_entities": ["customer_data", "AES-256"]
    }
  ],
  "entities": [...],
  "potential_aliases": [...],
  "extraction_metadata": {
    "model_used": "claude-sonnet-4.5",
    "extraction_date": "2024-01-30",
    "documents_processed": 12,
    "truths_extracted": 847
  }
}
```

**Product potential:** "Document Intelligence Package" - clients get structured mapping of their security posture from their own documentation.

---

## Success Criteria

1. **Accuracy** - Every truth has precise citation, no false claims
2. **Completeness** - Broad extraction, don't miss relevant information
3. **Transparency** - Agent can see all variants, all evidence
4. **Debuggability** - Synchronous operations, clear failure points
5. **Security** - Ephemeral storage, provable deletion
6. **Deliverability** - Export provides standalone value to clients

---

## Non-Goals

- **Real-time processing** - Extraction is batch, not streaming
- **Automatic conflict resolution** - Agents reason about conflicts
- **Entity disambiguation** - Store variants, let agents decide
- **Multi-tenant persistence** - Each assessment is isolated
- **Version control** - Fresh extraction per engagement
