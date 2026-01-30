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

Extract ALL factual statements from this section. Be comprehensive, not selective.

**What to extract:**
- System architecture (components, topology, transaction volumes, latency targets)
- Component specifications (versions, configurations, capacities, limits)
- Configuration values (timeouts, thresholds, rate limits, rotation schedules)
- Integration details (which vendor, which API, what protocol, what data flows)
- Operational processes (monitoring intervals, retention periods, update schedules)
- Security controls (encryption, authentication, access control, key management)
- Data characteristics (volumes, sensitivity, retention, locations)
- Performance metrics (throughput, latency, availability targets)
- Constraints and limitations (known issues, deprecated features, planned changes)

**Statement types:**
1. **Assertions** - Current facts (what IS): "System processes 10,000 transactions daily"
2. **Plans** - Future intentions (what WILL BE): "MFA planned for Q3 2024"
3. **Requirements** - Obligations (what MUST BE): "All data must be encrypted at rest"
4. **Recommendations** - Suggestions (what SHOULD BE): "Consider implementing rate limiting"

For each statement:
- Extract the exact quote or paraphrase faithfully
- Classify statement type based on tense/language
- Identify related entities (systems, technologies, data, etc.)
- Estimate confidence (0.0-1.0) - lower if vague or ambiguous
- Note source location (page, paragraph if available)

**Critical instructions:**
- Extract EVERY factual statement, not just "important" ones
- Include quantitative details: numbers, timeouts, limits, schedules, versions
- Include architectural details even if not explicitly "security controls"
- **INCLUDE NEGATIVE STATEMENTS**: "No incident response plan", "MFA not yet implemented", "Penetration testing not performed"
  Negative statements are truths - capture what is explicitly absent or not yet done
- Don't filter for relevance - extract everything, let workflow agents decide what matters
- Use exact quotes where possible
- Lower confidence if statement is vague, ambiguous, or inferred

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
