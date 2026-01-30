"""Prompts for LLM extraction."""

OVERVIEW_PROMPT = """You are analyzing a document to extract high-level structure and entities.

Document: {filename}
Full Text:
{text}

Extract:
1. Document purpose (1-2 sentences)
2. Main topics covered
3. Key entities mentioned (systems, technologies, people, organizations, data types)
4. Document type (architecture, policy, requirement, report, etc.)

Return JSON:
{{
  "purpose": "...",
  "topics": ["topic1", "topic2", ...],
  "entities": [
    {{"name": "entity_name", "entity_type": "system|technology|person|organization|data", "context": "brief context"}}
  ],
  "document_type": "..."
}}

Be comprehensive. Extract all entities even if mentioned briefly.
"""


SECTION_EXTRACTION_PROMPT = """You are extracting structured information from a document section.

Document Context:
- Filename: {filename}
- Purpose: {doc_purpose}
- Document Type: {doc_type}

Section: {section_title}
Content:
{section_content}

Extract:
1. **Truths** - Factual statements (what IS, not what's planned or required)
2. **Plans** - Future intentions (what WILL BE done)
3. **Requirements** - Obligations (what MUST BE done)
4. **Recommendations** - Suggestions (what SHOULD BE done)
5. **Entities** - Systems, technologies, people, organizations, data mentioned
6. **Relationships** - How entities relate (stores, integrates with, depends on, etc.)

For each truth/plan/requirement/recommendation:
- Extract the exact statement
- Identify entities involved
- Classify statement type
- Estimate confidence (0.0-1.0)

Return JSON:
{{
  "truths": [
    {{
      "statement": "exact statement from document",
      "statement_type": "assertion|plan|requirement|recommendation",
      "confidence": 0.95,
      "entities": ["entity1", "entity2"],
      "page": 5,
      "paragraph": 2
    }}
  ],
  "entities": [
    {{"name": "entity_name", "entity_type": "system|technology|person|organization|data", "context": "..."}}
  ],
  "relationships": [
    {{
      "entity_a": "system_a",
      "relationship_type": "stores|integrates_with|depends_on|encrypts|manages",
      "entity_b": "system_b",
      "evidence": "quote from text supporting this relationship",
      "confidence": 0.9
    }}
  ]
}}

Critical:
- Use exact quotes from the document for statements
- Don't invent information
- Lower confidence if ambiguous
- Statement type must match tense/language used
"""


CROSS_REFERENCE_PROMPT = """You are linking cross-references within a document.

Document: {filename}
All Sections:
{all_sections}

Find:
1. Explicit references ("see Section X", "as defined in Appendix B")
2. Implicit references (term defined in one section, used in another)
3. Policy references ("per security policy", "according to standards")

Return JSON:
{{
  "references": [
    {{
      "source_section": "section referencing",
      "target_section": "section being referenced",
      "reference_type": "explicit|implicit|policy",
      "linked_entities": ["entity1", "entity2"]
    }}
  ]
}}
"""
