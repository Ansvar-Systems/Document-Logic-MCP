"""Prompts for LLM extraction.

Prompt architecture:
- OVERVIEW_PROMPT: Pass 1 — high-level document understanding
- SECTION_EXTRACTION_PROMPT: Pass 2 — per-section truth/entity/relationship extraction
- CONTEXT_SUPPLEMENTS: Optional domain-specific additions appended to Pass 2 prompt
  when an analysis_context is specified (e.g., "stride_threat_modeling")
- SYNTHESIS_PROMPT: Pass 3 — cross-section consolidation (component registry,
  trust boundaries, implicit negatives, ambiguity flags)

The CONTEXT_SUPPLEMENTS pattern keeps the MCP general-purpose while allowing
callers to unlock domain-specific extraction intelligence. New domains can be
added by adding entries to the dict — no extraction core changes needed.
"""

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
      "relationship_type": "stores|integrates_with|depends_on|encrypts|manages|sends_data_to|receives_data_from",
      "entity_b": "system_b",
      "evidence": "quote from text supporting this relationship",
      "confidence": 0.9,
      "source_component": null,
      "destination_component": null,
      "data_transferred": null,
      "protocol_mechanism": null
    }}
  ]
}}

Critical:
- Use exact quotes from the document for statements
- Don't invent information
- Lower confidence if ambiguous
- Statement type must match tense/language used
{context_supplement}"""


# ─── Domain-specific prompt supplements ──────────────────────────────
#
# Appended to SECTION_EXTRACTION_PROMPT when analysis_context is specified.
# Each supplement adds focused extraction instructions WITHOUT removing
# or replacing the base extraction — the LLM still extracts everything,
# but pays additional attention to domain-relevant patterns.
#
# To add a new domain: add an entry to this dict with the domain key
# (matching what callers pass as analysis_context) and the prompt text.

CONTEXT_SUPPLEMENTS = {
    "stride_threat_modeling": """
**Additional extraction focus (Threat Modeling):**

- **Trust boundary crossings**: Identify every point where data crosses between
  different trust domains (e.g., internal network → cloud provider, application →
  third-party SaaS, organization → external partner, user → backend). For each
  crossing, capture it as a relationship with:
  - source_component: the sending system/domain
  - destination_component: the receiving system/domain
  - data_transferred: what data moves across
  - protocol_mechanism: how it moves (HTTPS, gRPC, AMQP, etc.)

- **Data flow directionality**: For EVERY data movement or integration, explicitly
  identify source_component and destination_component. "Full conversation history
  is transferred" should produce source_component="orchestration_layer",
  destination_component="genesys_cloud", data_transferred="conversation_history".
  Bidirectional flows should be two separate relationships.

- **Implicit negatives**: Flag security-relevant topics that are conspicuously
  ABSENT given what this section covers. This is contextual: if the section
  describes authentication flows but never mentions session revocation or token
  expiry, that absence is notable. If authentication is entirely out of scope,
  its absence is NOT notable. Add implicit negatives as truths with
  statement_type="assertion" and the prefix "IMPLICIT NEGATIVE:".

- **Ambiguity flagging**: When you encounter vague security language — words like
  "sanitized", "filtered", "encrypted", "secured", "validated", "hardened",
  "protected" — WITHOUT specifying the concrete mechanism (which algorithm, which
  library, which protocol version), create a truth with LOW confidence (0.3-0.5)
  and prefix the statement with "AMBIGUOUS:". Example: if the document says
  "inputs are sanitized", extract: "AMBIGUOUS: Inputs are sanitized (mechanism
  unspecified — unclear whether this means regex filtering, parameterized queries,
  HTML encoding, or other approach)".
""",

    "tprm_vendor_assessment": """
**Additional extraction focus (Vendor Assessment):**

- **Certification evidence**: Extract specific certification names, issuing bodies,
  scope descriptions, validity/expiry dates, and audit cycle frequency. Note
  whether certifications cover the specific service being assessed or only the
  vendor's broader organization.

- **Subprocessor chains**: Identify all mentioned subprocessors, fourth parties,
  and their roles. Capture which data each subprocessor accesses and under what
  contractual framework.

- **SLA commitments**: Extract specific numeric SLA values — uptime percentages,
  response times, resolution times, maintenance windows. Flag any SLA that lacks
  penalty/remedy clauses.

- **Data residency and sovereignty**: Capture all mentions of data storage
  locations, processing jurisdictions, and cross-border transfer mechanisms
  (SCCs, adequacy decisions, BCRs). Flag any ambiguity about where data actually
  resides vs. where it is processed.

- **Incident response obligations**: Extract notification timelines, escalation
  procedures, evidence preservation commitments, and root cause analysis
  obligations. Flag if any are missing.
""",
}


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


# ─── Synthesis prompt (Pass 3) ───────────────────────────────────────
#
# Runs after all sections are extracted. Receives a consolidated view of
# all truths, entities, and relationships, then produces:
# 1. Deduplicated component registry with evidence references
# 2. Trust boundary map from relationship + entity data
# 3. Implicit negatives (contextual gap detection)
# 4. Ambiguity flags for vague security language
#
# Token budget: The caller is responsible for checking whether the input
# fits the model's context window. If it doesn't, the caller should use
# chunked synthesis (see extractor.py).

SYNTHESIS_PROMPT = """You are consolidating extraction results from a document that was analyzed section-by-section.

**Document:** {filename}
**Purpose:** {doc_purpose}
**Type:** {doc_type}
**Analysis Context:** {analysis_context}
**Sections analyzed:** {section_count}

Below are ALL extracted truths, entities, and relationships from every section.
Your job is to consolidate them into four structured outputs.

=== EXTRACTED DATA ===
{extracted_data}
=== END EXTRACTED DATA ===

Produce a JSON response with these four sections:

**1. component_registry** — Deduplicated inventory of all systems, services, and
components mentioned across the document. Merge duplicate references (e.g.,
"Azure OpenAI" mentioned in sections 2, 5, and 7 becomes one entry).

**2. trust_boundaries** — Every point where data crosses between different trust
domains. Infer trust domains from the document context (e.g., "internal network",
"cloud provider", "third-party SaaS", "external partner", "end user").

**3. implicit_negatives** — Security-relevant topics that are conspicuously ABSENT
given what the document covers. This MUST be contextual:
- If the document describes authentication but never mentions session management → notable
- If the document is about data retention and doesn't mention authentication → NOT notable
- Consider: backup/DR, incident response, key rotation, input validation, rate limiting,
  logging/audit trails, rollback procedures, access reviews, patch management, dependency
  management — but ONLY flag those that are relevant to the document's scope.

**4. ambiguities** — Vague security language that lacks mechanism specifics. Look for:
"sanitized", "filtered", "encrypted", "secured", "validated", "hardened", "protected",
"restricted", "monitored" — when used without specifying HOW.

Return JSON:
{{
  "component_registry": [
    {{
      "name": "Azure OpenAI",
      "component_type": "third_party_ai",
      "evidence_refs": ["Section: Architecture Overview, Page: 3", "Section: Integration, Page: 7"],
      "properties": {{"vendor": "Microsoft", "protocol": "HTTPS REST API"}}
    }}
  ],
  "trust_boundaries": [
    {{
      "source_domain": "bank_internal_network",
      "destination_domain": "azure_cloud",
      "data_transferred": "customer queries, conversation context",
      "protocol_mechanism": "HTTPS/TLS 1.3",
      "components_involved": ["orchestration_layer", "azure_openai"],
      "evidence": "Section: Architecture, 'All API calls to Azure OpenAI use...'"
    }}
  ],
  "implicit_negatives": [
    {{
      "missing_topic": "session revocation",
      "relevance_context": "Document describes authentication flows and token handling but never addresses how sessions are invalidated or tokens revoked",
      "related_topics_present": ["authentication", "JWT tokens", "session management"]
    }}
  ],
  "ambiguities": [
    {{
      "vague_term": "sanitized",
      "source_statement": "User inputs are sanitized before processing",
      "section": "Security Controls",
      "clarification_needed": "Sanitization mechanism unspecified — could mean regex filtering, parameterized queries, HTML encoding, or input length limits"
    }}
  ]
}}

Critical:
- Deduplicate aggressively in component_registry — same component mentioned in different sections = one entry
- Trust boundaries must be inferred from actual data flows in the document, not invented
- Implicit negatives must be CONTEXTUAL — only flag absences that matter given what the document covers
- Ambiguities must reference actual extracted statements, not hypothetical ones
- Every entry must trace back to extracted evidence — no fabrication
"""
