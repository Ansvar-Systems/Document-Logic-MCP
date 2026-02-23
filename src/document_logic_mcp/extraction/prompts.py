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
**Additional extraction focus (Vendor Assessment - v3.0):**

- **Vendor entity normalization**: Extract ALL variant names for the vendor
  (legal name, trading names, abbreviations, parent company names, subsidiaries).
  Identify the most formal version as the canonical name. Example: "Acme
  Corporation" (canonical), with aliases ["ACME", "Acme Corp.", "Acme Cloud Inc."].
  Extract Legal Entity Identifier (LEI) if mentioned anywhere in documents.
  Capture jurisdiction of incorporation (country, state/province if specified).

- **Key personnel identification**: Extract names and roles for senior personnel,
  especially: CEO, CFO, CTO, CISO, DPO (Data Protection Officer), Security Officer,
  Compliance Officer. Note where each person is mentioned (DPA signature, org chart,
  certificate signatory, contact lists).

- **Certification evidence**: Extract specific certification names (ISO 27001, SOC 2,
  PCI DSS, etc.), issuing bodies, scope descriptions, validity/expiry dates, and
  audit cycle frequency. Note whether certifications cover the specific service
  being assessed or only the vendor's broader organization. Capture certificate
  numbers if present.

- **Subprocessor chains**: Identify all mentioned subprocessors, fourth parties,
  and their roles. For EACH subprocessor: canonical name, aliases, jurisdiction,
  data processing activities (e.g., "cloud infrastructure", "email delivery"),
  and audit rights. Capture the full subprocessor hierarchy if multiple levels
  exist (vendor → sub-processor → sub-sub-processor).

- **SLA commitments**: Extract specific numeric SLA values — uptime percentages,
  response times (P1/P2/P3), resolution times, maintenance windows, RTO (Recovery
  Time Objective), RPO (Recovery Point Objective). Flag any SLA that lacks
  penalty/remedy clauses. Note if SLAs vary by service tier.

- **Data residency and sovereignty**: Capture all mentions of data storage
  locations, processing jurisdictions, and cross-border transfer mechanisms
  (SCCs, adequacy decisions, BCRs). Flag any ambiguity about where data actually
  resides vs. where it is processed. Extract data retention periods and deletion
  commitments.

- **Incident response obligations**: Extract notification timelines (e.g., "72 hours"),
  escalation procedures, evidence preservation commitments, root cause analysis
  obligations, and breach notification protocols. Flag if any are missing.

- **Audit and inspection rights**: Extract audit frequency, advance notice periods,
  scope limitations, and cost allocation. Note if vendor allows on-site inspections
  vs. only providing audit reports.

**CRITICAL for all entities (vendor, subprocessor, personnel, certification):**
Every extracted entity MUST include source_document_sections with:
- document_name: exact filename (e.g., "DPA - Acme Corp 2024.pdf")
- section: section title or number (e.g., "Annex A: Subprocessors", "§3.2")
- page: specific page number (not range)
- excerpt: exact quote from document (max 200 chars)

If you cannot determine the source for an entity, DO NOT extract it.
""",

    "compliance_mapping": """
**Additional extraction focus (Compliance Mapping):**

- **Legal obligations**: Extract EVERY obligation, requirement, or duty imposed by
  the regulation. For each obligation capture:
  - The exact article/section reference (e.g., "Article 33(1)", "§ 164.312(a)(1)")
  - The responsible party (who must comply — controller, processor, operator,
    covered entity, financial institution, etc.)
  - The action required (what must be done)
  - Any deadline or time constraint (e.g., "within 72 hours", "by 17 October 2024",
    "annually", "without undue delay")
  - Conditions or triggers (when the obligation applies)
  - Exemptions or exceptions (who/what is excluded)
  Create truths with statement_type="requirement" for each obligation.

- **Temporal requirements**: Pay special attention to ALL time-bound requirements:
  - Notification windows (breach notification deadlines, reporting periods)
  - Implementation deadlines (transposition dates, compliance deadlines)
  - Review/renewal periods (periodic assessments, audit cycles, certification renewals)
  - Retention periods (data retention, record-keeping obligations)
  - Grace periods and transitional provisions
  For each, extract the exact duration/date AND the triggering event or start point.

- **Penalty and enforcement structures**: Extract all penalty provisions including:
  - Maximum fine amounts (absolute values AND revenue-based calculations,
    e.g., "up to EUR 10,000,000 or 2% of annual worldwide turnover")
  - Tiered penalty structures (distinguish between levels/categories of violations)
  - Criminal sanctions (imprisonment, personal liability)
  - Administrative measures (cease-and-desist, suspension of operations,
    withdrawal of certification)
  - Enforcement bodies (which authority enforces — DPA, sectoral regulator, etc.)
  - Aggravating and mitigating factors for penalty calculation
  - Private right of action / right to compensation

- **Cross-regulation references**: Identify every reference to other legal
  instruments, standards, or frameworks:
  - Explicit references ("in accordance with Regulation (EU) 2016/679",
    "as defined in Directive 2013/40/EU")
  - Standard references (ISO 27001, NIST CSF, CIS Controls, etc.)
  - Mutual recognition or equivalence clauses
  - Relationship to other laws (lex specialis, complementary, superseding)
  - Delegated/implementing acts referenced
  Create relationships with relationship_type="references" for each cross-reference.

- **Scope definitions**: Extract the complete applicability scope:
  - Entity types covered (by size, sector, function — e.g., "essential entities",
    "operators of essential services", "large enterprises")
  - Entity types excluded (SME exemptions, sector carve-outs)
  - Data types in scope (personal data, health data, financial data, etc.)
  - Geographic scope (territorial applicability, extraterritorial reach)
  - Sectoral scope (which industries/sectors, Annex references)
  - Material scope (which activities — processing, transferring, storing, etc.)
  - Thresholds for applicability (revenue thresholds, employee counts,
    data volume thresholds)

- **Definitions**: Extract all defined terms with their exact definitions and
  article references. Regulatory definitions are critical for scope determination.
  Create truths with statement_type="assertion" for each definition.

**CRITICAL for compliance mapping:**
- Use EXACT article/section references — never approximate ("Article 5" not "around Article 5")
- Preserve regulatory language precisely — do not paraphrase obligation text
- Distinguish between mandatory ("shall", "must") and discretionary ("may", "should") language
- Flag delegated/implementing acts that may contain additional obligations not in the primary text
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

**Context-specific synthesis (if analysis_context="compliance_mapping"):**

When consolidating regulatory/legal documents, ADD these additional sections to the
output JSON (in addition to the 4 base sections above):

**5. obligation_registry** — All legal obligations extracted, deduplicated and consolidated.
For each obligation: obligation_id (OBL-NNN), article_reference, obligation_text (exact
regulatory language), responsible_party, action_required, deadline (if any), conditions,
exemptions, obligation_type (notification/implementation/operational/reporting/record_keeping),
and evidence citation.

**6. deadline_inventory** — All temporal requirements consolidated. For each deadline:
deadline_id (DL-NNN), requirement description, article_reference, duration or date,
trigger_event (what starts the clock), deadline_type (notification_window/implementation_deadline/
review_period/retention_period/grace_period/transitional_provision), responsible_party,
and evidence citation.

**7. penalty_structures** — All enforcement mechanisms. For each penalty tier:
penalty_id (PEN-NNN), article_reference, violation_category, max_fine_absolute,
max_fine_revenue_based (if applicable), calculation_method, criminal_sanctions (if any),
administrative_measures (list), enforcement_body, aggravating_factors, mitigating_factors,
private_right_of_action (boolean), and evidence citation.

**8. cross_regulation_references** — Every reference to external legal instruments.
For each: reference_id (XREF-NNN), source_article (where in this document),
referenced_instrument (full name + citation), reference_type (complementary/superseding/
lex_specialis/delegated_act/implementing_act/standard/equivalence), relationship_description,
and evidence citation.

**9. scope_definitions** — Complete applicability map. Contains:
- entity_types_included: array of {entity_type, description, article_reference, evidence}
- entity_types_excluded: array of {entity_type, description, article_reference, evidence}
- data_types_in_scope: array of data type strings
- geographic_scope: territorial applicability description
- sectoral_scope: array of sector/industry strings
- material_scope: which activities are covered
- applicability_thresholds: array of {threshold_type, value, article_reference}

**Context-specific synthesis (if analysis_context="tprm_vendor_assessment"):**

When consolidating vendor assessment documents, ADD these additional sections to the
output JSON (in addition to the 4 base sections above):

**5. vendor_registry** — Canonical vendor entity with all name variants, LEI, jurisdiction.
Merge all vendor name mentions across documents into ONE entry with:
- canonical_name: most formal/legal name
- aliases: all other names found (trading names, abbreviations, etc.)
- lei: Legal Entity Identifier if found
- jurisdiction: country + state/province of incorporation
- source_document_sections: array of {document_name, section, page, excerpt}

**6. certification_catalog** — All certifications mentioned, deduplicated across documents.
For each cert: type (ISO 27001, SOC 2, etc.), scope, validity dates, audit body, source.

**7. subprocessor_inventory** — All subprocessors with canonical names, aliases, jurisdictions,
data processing activities, and audit rights. Include source citations for each.

**8. key_personnel** — Senior staff (CEO, CFO, DPO, CISO, etc.) with roles and source citations.

**9. sla_commitments** — All numeric SLA values (uptime %, RTO, RPO, response times).

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
  ],

  // ─── TPRM-specific fields (only if analysis_context="tprm_vendor_assessment") ───

  "vendor_registry": {{
    "canonical_name": "Acme Corporation",
    "aliases": ["ACME", "Acme Corp.", "Acme Cloud Inc."],
    "lei": "123456789012345678XX",
    "jurisdiction": "Delaware, USA",
    "source_document_sections": [
      {{
        "document_name": "DPA - Acme Corp 2024.pdf",
        "section": "1. Parties",
        "page": 1,
        "excerpt": "This agreement is between Customer and Acme Corporation (LEI: 123456789012345678XX), incorporated in Delaware"
      }},
      {{
        "document_name": "ISO 27001 Certificate.pdf",
        "section": "Certificate Header",
        "page": 1,
        "excerpt": "This certificate is awarded to Acme Corporation, 123 Main St, Wilmington, DE"
      }}
    ]
  }},
  "certification_catalog": [
    {{
      "type": "ISO 27001",
      "canonical_name": "ISO/IEC 27001:2013",
      "scope": "Cloud platform services and data processing operations",
      "validity": {{"from": "2023-01-15", "to": "2026-01-14"}},
      "audit_body": "BSI Group",
      "source_document_sections": [
        {{
          "document_name": "ISO 27001 Certificate.pdf",
          "section": "Certificate Body",
          "page": 1,
          "excerpt": "Certificate No. IS 654321. Valid: 15 Jan 2023 - 14 Jan 2026. Certification Body: BSI Group"
        }}
      ]
    }}
  ],
  "subprocessor_inventory": [
    {{
      "canonical_name": "Amazon Web Services",
      "aliases": ["AWS", "aws inc"],
      "jurisdiction": "United States",
      "data_processing_activities": ["Cloud infrastructure hosting", "Data storage (S3 buckets)"],
      "audit_rights": "Customer may audit AWS annually with 30 days notice per AWS DPA",
      "source_document_sections": [
        {{
          "document_name": "DPA - Acme Corp 2024.pdf",
          "section": "Annex A: Subprocessors",
          "page": 12,
          "excerpt": "Amazon Web Services, Inc. (AWS) - Cloud infrastructure hosting for production systems"
        }}
      ]
    }}
  ],
  "key_personnel": [
    {{
      "name": "John Smith",
      "role": "CEO",
      "source_document_sections": [
        {{
          "document_name": "DPA - Acme Corp 2024.pdf",
          "section": "13. Notices",
          "page": 8,
          "excerpt": "For Acme Corporation: John Smith, CEO, john.smith@acme.com"
        }}
      ]
    }}
  ],
  "sla_commitments": [
    {{
      "metric": "uptime",
      "value": "99.9%",
      "scope": "Production API endpoints",
      "penalty": "10% monthly credit for downtime >0.1%",
      "source_document_sections": [
        {{
          "document_name": "SLA - Acme Services 2024.pdf",
          "section": "2. Service Level Objectives",
          "page": 3,
          "excerpt": "Service availability: 99.9% uptime measured monthly for production API endpoints"
        }}
      ]
    }}
  ],

  // ─── Compliance-specific fields (only if analysis_context="compliance_mapping") ───

  "obligation_registry": [
    {{
      "obligation_id": "OBL-001",
      "article_reference": "Article 33(1)",
      "obligation_text": "The controller shall notify the supervisory authority of a personal data breach within 72 hours of becoming aware of it",
      "responsible_party": "controller",
      "action_required": "Notify supervisory authority of personal data breach",
      "deadline": "72 hours from awareness",
      "conditions": "Unless the breach is unlikely to result in a risk to rights and freedoms",
      "exemptions": "Breach unlikely to result in risk to natural persons' rights and freedoms",
      "obligation_type": "notification",
      "evidence": "Section: Breach Notification, Page: 45"
    }}
  ],
  "deadline_inventory": [
    {{
      "deadline_id": "DL-001",
      "requirement": "Breach notification to supervisory authority",
      "article_reference": "Article 33(1)",
      "duration": "72 hours",
      "trigger_event": "Becoming aware of a personal data breach",
      "deadline_type": "notification_window",
      "responsible_party": "controller",
      "evidence": "Section: Breach Notification, Page: 45"
    }}
  ],
  "penalty_structures": [
    {{
      "penalty_id": "PEN-001",
      "article_reference": "Article 83(5)",
      "violation_category": "Infringement of basic principles for processing",
      "max_fine_absolute": "EUR 20,000,000",
      "max_fine_revenue_based": "4% of total worldwide annual turnover",
      "calculation_method": "whichever is higher",
      "criminal_sanctions": null,
      "administrative_measures": ["cease processing", "suspension of data flows"],
      "enforcement_body": "National supervisory authority (DPA)",
      "aggravating_factors": ["intentional character", "failure to cooperate"],
      "mitigating_factors": ["degree of cooperation", "measures taken to mitigate damage"],
      "private_right_of_action": true,
      "evidence": "Section: Penalties, Page: 82"
    }}
  ],
  "cross_regulation_references": [
    {{
      "reference_id": "XREF-001",
      "source_article": "Article 2(3)",
      "referenced_instrument": "Regulation (EU) 2016/679 (GDPR)",
      "reference_type": "complementary",
      "relationship_description": "Processing of personal data under this regulation is subject to GDPR",
      "evidence": "Section: Scope, Page: 3"
    }}
  ],
  "scope_definitions": {{
    "entity_types_included": [
      {{
        "entity_type": "essential entities",
        "description": "Entities in sectors listed in Annex I exceeding medium-sized enterprise thresholds",
        "article_reference": "Article 3(1)",
        "evidence": "Section: Scope, Page: 5"
      }}
    ],
    "entity_types_excluded": [
      {{
        "entity_type": "micro enterprises",
        "description": "Enterprises with fewer than 10 employees and annual turnover below EUR 2 million",
        "article_reference": "Article 2(1)",
        "evidence": "Section: Scope, Page: 3"
      }}
    ],
    "data_types_in_scope": ["personal data", "network and information system data"],
    "geographic_scope": "EU Member States, with extraterritorial reach for entities providing services in the EU",
    "sectoral_scope": ["energy", "transport", "banking", "health", "digital infrastructure"],
    "material_scope": "Security of network and information systems",
    "applicability_thresholds": [
      {{
        "threshold_type": "enterprise_size",
        "value": "Medium-sized or larger (50+ employees or EUR 10M+ turnover)",
        "article_reference": "Article 2(1)"
      }}
    ]
  }}
}}

Critical:
- Deduplicate aggressively in component_registry — same component mentioned in different sections = one entry
- Trust boundaries must be inferred from actual data flows in the document, not invented
- Implicit negatives must be CONTEXTUAL — only flag absences that matter given what the document covers
- Ambiguities must reference actual extracted statements, not hypothetical ones
- Every entry must trace back to extracted evidence — no fabrication
"""
