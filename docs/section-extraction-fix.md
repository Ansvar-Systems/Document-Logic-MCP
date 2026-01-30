# Section-by-Section Extraction Fix

## Problem Identified

**Symptom**: Only 24 truths extracted from tough_test_document.docx when 60-80+ expected

**Root Cause**: Extraction was processing entire document as one blob instead of section-by-section

**Evidence**:
- Parser correctly found all 9 sections ✓
- Database showed `sections_count = 9` ✓
- But sections were never stored in database ✗
- Extractor reconstructed fake single-section ParseResult ✗
- LLM received entire 9607-char document as one chunk ✗
- Extraction stopped after ~3 sections worth of content ✗

## Code Changes

### 1. Added Sections Table (`database.py`)

```python
# Sections table
await db.execute("""
    CREATE TABLE IF NOT EXISTS sections (
        section_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        section_index INTEGER NOT NULL,
        FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
    )
""")

# Index for retrieval
await db.execute(
    "CREATE INDEX IF NOT EXISTS idx_sections_doc_id ON sections(doc_id)"
)
```

### 2. Store Sections During Parsing (`tools.py:parse_document_tool`)

```python
# Store sections
for idx, section in enumerate(parse_result.sections):
    section_id = str(uuid.uuid4())
    await conn.execute("""
        INSERT INTO sections (section_id, doc_id, title, content, section_index)
        VALUES (?, ?, ?, ?, ?)
    """, (
        section_id,
        doc_id,
        section.title,
        section.content,
        idx
    ))
```

### 3. Retrieve and Loop Through Sections (`tools.py:extract_document_tool`)

**Before:**
```python
# Fake single section
parse_result = ParseResult(
    filename=filename,
    sections=[Section(title="Document", content=raw_text)],  # ← One blob
    raw_text=raw_text,
    page_count=1,
    metadata={}
)

# Extract from fake section
section_extraction = await extractor.extract_section(
    section_title="Document",  # ← Only one extraction call
    section_content=raw_text,
    doc_context=overview,
    filename=filename,
    page=1
)
```

**After:**
```python
# Retrieve actual sections from database
cursor = await conn.execute(
    "SELECT title, content FROM sections WHERE doc_id = ? ORDER BY section_index",
    (doc_id,)
)
section_rows = await cursor.fetchall()
sections = [Section(title=row["title"], content=row["content"]) for row in section_rows]

# Reconstruct ParseResult with actual sections
parse_result = ParseResult(
    filename=filename,
    sections=sections,  # ← All 9 sections
    raw_text=raw_text,
    page_count=1,
    metadata={}
)

# Extract from EACH section
logger.info(f"Pass 2: Extracting truths from {len(sections)} sections...")
all_truths = []
all_entities = []
all_relationships = []

for idx, section in enumerate(sections):
    logger.info(f"  Extracting section {idx + 1}/{len(sections)}: {section.title}...")
    section_extraction = await extractor.extract_section(
        section_title=section.title,
        section_content=section.content,  # ← Individual section content
        doc_context=overview,
        filename=filename,
        page=None
    )

    all_truths.extend(section_extraction.truths)
    all_entities.extend(section_extraction.entities)
    all_relationships.extend(section_extraction.relationships)

# Store all extracted data
await storage.store_truths(doc_id, all_truths)
await storage.store_entities(doc_id, all_entities)
await storage.store_relationships(doc_id, all_relationships)
```

## Expected Impact

**Before Fix:**
- Tough document: 24 truths (only sections 1-3 processed)
- Simple document: 32 truths (but was also incomplete)

**After Fix:**
- Tough document: 60-80+ truths expected (all 9 sections)
- Each section gets focused LLM processing
- Missing content from sections 4-9 will now be captured:
  - Section 4: Infrastructure & Network (Kubernetes, ZPA, Cloudflare, Palo Alto)
  - Section 5: Third-Party Risk (Temenos, Finastra, Nets, GAP statements)
  - Section 6: Security Operations (SOC, Splunk, MTTD/MTTR, IR plan issues)
  - Section 7: Regulatory Compliance (DORA 73% vs 45-50% conflict, PCI-DSS gaps)
  - Section 8: Recommendations (HIGH/MEDIUM priorities)

## Next Steps

1. Delete old database: `data/tough_test.db`
2. Re-run extraction through MCP server
3. Verify 60-80+ truths extracted
4. Verify entities from all sections captured
5. Verify aliases detected (NFSP = Project Odin = CTE)
6. Verify GAP statements from Section 5 captured
7. Verify DORA conflict from Section 7 captured

## Testing

The test script `test_tough_document_fixed.py` was created but requires ANTHROPIC_API_KEY. Since the MCP server runs through Claude Desktop with the API key already configured, the proper way to test is:

1. Restart the MCP server
2. Use `parse_document` tool on tough_test_document.docx
3. Use `extract_document` tool on the returned doc_id
4. Use `export_assessment` tool to generate markdown report
5. Verify comprehensive extraction

Alternatively, set ANTHROPIC_API_KEY and run:
```bash
source .venv/bin/activate
export ANTHROPIC_API_KEY="your-key-here"
python test_tough_document_fixed.py
```
