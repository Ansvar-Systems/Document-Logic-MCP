"""Document extraction using LLM.

This module supports two modes:
1. Direct Anthropic API (legacy - requires ANTHROPIC_API_KEY)
2. LLM Gateway (recommended - uses configured extraction model)

Set LLM_GATEWAY_URL environment variable to use gateway mode.

Extraction pipeline:
- Pass 1: extract_overview() — high-level document understanding
- Pass 2: extract_section() — per-section truths, entities, relationships
  Optionally augmented with domain-specific prompts via analysis_context
- Pass 3: synthesize() — cross-section consolidation (component registry,
  trust boundaries, implicit negatives, ambiguity flags)
  Only runs when analysis_context is provided.
"""

import logging
import json
import re
import uuid
import os
from typing import Optional, List
import httpx
from anthropic import Anthropic
from .prompts import (
    OVERVIEW_PROMPT,
    SECTION_EXTRACTION_PROMPT,
    CONTEXT_SUPPLEMENTS,
    SYNTHESIS_PROMPT,
)
from .schemas import (
    DocumentOverview,
    SectionExtraction,
    ExtractedEntity,
    ExtractedTruth,
    ExtractedRelationship,
    ExtractionSynthesis,
    ComponentEntry,
    TrustBoundaryCrossing,
    ImplicitNegative,
    AmbiguityFlag,
    ObligationEntry,
    DeadlineEntry,
    PenaltyEntry,
    CrossRegulationReference,
    ScopeEntityType,
    ApplicabilityThreshold,
    ScopeDefinition,
    StatementType,
)
from ..parsers.base import ParseResult

logger = logging.getLogger(__name__)


class DocumentExtractor:
    """Extract structured information from parsed documents.

    Supports two modes:
    - Gateway mode: Uses LLM Gateway (set LLM_GATEWAY_URL)
    - Direct mode: Uses Anthropic API directly (set ANTHROPIC_API_KEY)
    """

    def __init__(
        self,
        llm_client: Optional[Anthropic] = None,
        extraction_model_override: Optional[str] = None
    ):
        """Initialize extractor with LLM client or gateway.

        Args:
            llm_client: Optional Anthropic client (for direct mode only)
            extraction_model_override: Optional model override (takes precedence over env var)
        """
        self.gateway_url = os.getenv("LLM_GATEWAY_URL")
        self.gateway_token = os.getenv("LLM_GATEWAY_API_KEY", "")
        # Use override if provided, otherwise fall back to env var
        self.extraction_model = (
            extraction_model_override
            or os.getenv("EXTRACTION_MODEL", "claude-sonnet-4-20250514")
        )

        if self.gateway_url:
            if not self.gateway_token:
                raise ValueError(
                    "LLM_GATEWAY_API_KEY must be set when LLM_GATEWAY_URL is configured"
                )
            logger.info(f"Using LLM Gateway mode: {self.gateway_url}, model: {self.extraction_model}")
            self.llm = None
        else:
            logger.info("Using Direct Anthropic API mode")
            self.llm = llm_client or Anthropic()

    async def _call_llm(self, prompt: str, max_tokens: int = 65536) -> str:
        """Call LLM via gateway or direct API.

        Args:
            prompt: The prompt to send
            max_tokens: Maximum tokens in response. Default 65536 to accommodate
                        reasoning models (GPT-5) that consume tokens on internal
                        chain-of-thought before producing visible output.

        Returns:
            LLM response text
        """
        if self.gateway_url:
            # Parse extraction_model if it contains provider prefix (e.g., "ollama/llama3.1")
            model = self.extraction_model
            provider = None
            if "/" in self.extraction_model:
                provider, model = self.extraction_model.split("/", 1)
                logger.info(f"Parsed model format: provider='{provider}', model='{model}'")

            # Build payload
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens
            }
            if provider:
                payload["provider"] = provider

            # Gateway mode - call LLM Gateway with service API key
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(
                    f"{self.gateway_url}/api/v1/chat/completions",
                    headers={
                        "X-Service-API-Key": self.gateway_token,
                        "Content-Type": "application/json"
                    },
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

                # Extract content from gateway response
                choices = data.get("choices", [])
                if not choices:
                    raise ValueError(
                        f"LLM Gateway returned no choices. "
                        f"Model: {data.get('model')}, response keys: {list(data.keys())}"
                    )

                message = choices[0].get("message", {})
                content = message.get("content")
                finish_reason = choices[0].get("finish_reason", "unknown")

                if not content:
                    # Content is None or empty - log the full response for debugging
                    logger.error(
                        f"LLM returned empty content. "
                        f"finish_reason={finish_reason}, "
                        f"model={data.get('model')}, "
                        f"message_keys={list(message.keys())}"
                    )
                    raise ValueError(
                        f"LLM returned empty content (finish_reason={finish_reason}). "
                        f"The model may have refused, timed out, or returned tool_calls instead of text."
                    )

                if finish_reason == "length":
                    logger.warning(
                        "LLM response truncated (finish_reason=length, model=%s). "
                        "Output may contain incomplete JSON.",
                        data.get("model"),
                    )

                return content
        else:
            # Direct Anthropic API mode
            response = self.llm.messages.create(
                model=self.extraction_model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text

    @staticmethod
    def _parse_json_response(text: str) -> dict:
        """Extract and parse JSON from LLM response text.

        Handles common LLM output quirks:
        - Markdown code fences (```json ... ```)
        - Leading/trailing whitespace or text before/after JSON
        - Raw JSON without any wrapping
        """
        # Try direct parse first
        stripped = text.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        # Strip markdown code fences
        fence_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', stripped, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Find first { to last } (outermost JSON object)
        first_brace = stripped.find('{')
        last_brace = stripped.rfind('}')
        if first_brace != -1 and last_brace > first_brace:
            try:
                return json.loads(stripped[first_brace:last_brace + 1])
            except json.JSONDecodeError:
                pass

        # Attempt truncated JSON repair: close open brackets/braces
        if first_brace != -1:
            fragment = stripped[first_brace:]
            repaired = DocumentExtractor._repair_truncated_json(fragment)
            if repaired is not None:
                logger.warning("Recovered truncated JSON via bracket repair")
                return repaired

        # Nothing worked - log what we got and raise
        preview = stripped[:200] if len(stripped) > 200 else stripped
        raise ValueError(
            f"Could not extract valid JSON from LLM response. "
            f"Response preview: {preview!r}"
        )

    @staticmethod
    def _repair_truncated_json(fragment: str) -> Optional[dict]:
        """Try to repair truncated JSON by closing open brackets and braces.

        Works for common LLM truncation where the response is valid JSON
        up to the point of truncation (e.g., max_tokens hit mid-array).
        """
        # Strip any trailing incomplete string value
        # e.g., '..."entities": ["ICT ' → '..."entities": ['
        import re as _re
        # Remove trailing incomplete string (unmatched quote)
        cleaned = _re.sub(r',?\s*"[^"]*$', '', fragment)
        # Remove trailing comma if present
        cleaned = _re.sub(r',\s*$', '', cleaned)

        # Count open brackets/braces and close them
        opens = []
        in_string = False
        escape_next = False
        for ch in cleaned:
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in ('{', '['):
                opens.append(ch)
            elif ch == '}' and opens and opens[-1] == '{':
                opens.pop()
            elif ch == ']' and opens and opens[-1] == '[':
                opens.pop()

        # Close remaining open brackets/braces in reverse order
        closing = ''.join(']' if o == '[' else '}' for o in reversed(opens))
        candidate = cleaned + closing

        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

    async def extract_overview(self, parse_result: ParseResult) -> DocumentOverview:
        """Pass 1: Extract high-level document overview."""
        prompt = OVERVIEW_PROMPT.format(
            filename=parse_result.filename,
            text=parse_result.raw_text  # Full document - no truncation
        )

        response_text = await self._call_llm(prompt)
        result = self._parse_json_response(response_text)

        return DocumentOverview(
            doc_id=str(uuid.uuid4()),
            purpose=result["purpose"],
            topics=result["topics"],
            entities=[
                ExtractedEntity(**e) for e in result["entities"]
            ],
            document_type=result["document_type"]
        )

    async def extract_section(
        self,
        section_title: str,
        section_content: str,
        doc_context: DocumentOverview,
        filename: str,
        page: Optional[int] = None,
        analysis_context: Optional[str] = None
    ) -> SectionExtraction:
        """Pass 2: Extract truths, entities, relationships from section.

        Args:
            section_title: Title of the section being extracted
            section_content: Full text content of the section
            doc_context: Overview from Pass 1
            filename: Document filename
            page: Optional page number hint
            analysis_context: Optional domain context (e.g., "stride_threat_modeling")
                that appends domain-specific extraction instructions to the prompt.
                See CONTEXT_SUPPLEMENTS in prompts.py for available contexts.
        """
        # Resolve context supplement (empty string if no context or unknown context)
        context_supplement = ""
        if analysis_context:
            context_supplement = CONTEXT_SUPPLEMENTS.get(analysis_context, "")
            if not context_supplement:
                logger.warning(
                    f"Unknown analysis_context '{analysis_context}' — "
                    f"available contexts: {list(CONTEXT_SUPPLEMENTS.keys())}. "
                    f"Proceeding with base extraction only."
                )

        prompt = SECTION_EXTRACTION_PROMPT.format(
            filename=filename,
            doc_purpose=doc_context.purpose,
            doc_type=doc_context.document_type,
            section_title=section_title,
            section_content=section_content,  # Full section - no truncation
            context_supplement=context_supplement,
        )

        response_text = await self._call_llm(prompt)
        result = self._parse_json_response(response_text)

        return SectionExtraction(
            section_title=section_title,
            truths=[
                ExtractedTruth(
                    statement=t["statement"],
                    section=section_title,
                    page=t.get("page") or page,
                    paragraph=t.get("paragraph"),
                    statement_type=StatementType(t["statement_type"]),
                    confidence=t["confidence"],
                    entities=t["entities"],
                    document_name=filename,
                )
                for t in result["truths"]
            ],
            entities=[
                ExtractedEntity(**e) for e in result["entities"]
            ],
            relationships=[
                ExtractedRelationship(
                    entity_a=r["entity_a"],
                    relationship_type=r["relationship_type"],
                    entity_b=r["entity_b"],
                    evidence=r["evidence"],
                    confidence=r["confidence"],
                    source_component=r.get("source_component"),
                    destination_component=r.get("destination_component"),
                    data_transferred=r.get("data_transferred"),
                    protocol_mechanism=r.get("protocol_mechanism"),
                )
                for r in result["relationships"]
            ]
        )

    async def synthesize(
        self,
        filename: str,
        doc_context: DocumentOverview,
        all_truths: List[ExtractedTruth],
        all_entities: List[ExtractedEntity],
        all_relationships: List[ExtractedRelationship],
        section_count: int,
        analysis_context: str,
    ) -> ExtractionSynthesis:
        """Pass 3: Cross-section synthesis for consolidated intelligence.

        Produces a component registry, trust boundary map, implicit negatives,
        and ambiguity flags from the aggregated extraction data.

        Token budget: Estimates the input size and truncates extracted data if
        it would exceed 80% of the model's context window. Truncation preserves
        entities and relationships (smaller) and trims truths (largest).

        Args:
            filename: Document filename
            doc_context: Overview from Pass 1
            all_truths: All truths from all sections (Pass 2)
            all_entities: All entities from all sections (Pass 2)
            all_relationships: All relationships from all sections (Pass 2)
            section_count: Number of sections analyzed
            analysis_context: Domain context string (required for synthesis)

        Returns:
            ExtractionSynthesis with component_registry, trust_boundaries,
            implicit_negatives, and ambiguities.
        """
        # Build extracted data payload for the synthesis prompt
        extracted_data = self._build_synthesis_input(
            all_truths, all_entities, all_relationships
        )

        # No truncation — send all extracted data to synthesis.
        # The LLM provider enforces context window limits with a clear error.

        prompt = SYNTHESIS_PROMPT.format(
            filename=filename,
            doc_purpose=doc_context.purpose,
            doc_type=doc_context.document_type,
            analysis_context=analysis_context,
            section_count=section_count,
            extracted_data=extracted_data,
        )

        logger.info(
            f"Pass 3: Running synthesis ({len(prompt)} chars prompt, "
            f"{len(all_truths)} truths, {len(all_entities)} entities, "
            f"{len(all_relationships)} relationships)"
        )

        response_text = await self._call_llm(prompt)
        result = self._parse_json_response(response_text)

        # Parse compliance mapping fields (only present when analysis_context="compliance_mapping")
        scope_def_raw = result.get("scope_definitions")
        scope_definitions = None
        if scope_def_raw and isinstance(scope_def_raw, dict):
            scope_definitions = ScopeDefinition(
                entity_types_included=[
                    ScopeEntityType(
                        entity_type=et["entity_type"],
                        description=et.get("description", ""),
                        article_reference=et.get("article_reference"),
                        evidence=et.get("evidence"),
                    )
                    for et in scope_def_raw.get("entity_types_included", [])
                ],
                entity_types_excluded=[
                    ScopeEntityType(
                        entity_type=et["entity_type"],
                        description=et.get("description", ""),
                        article_reference=et.get("article_reference"),
                        evidence=et.get("evidence"),
                    )
                    for et in scope_def_raw.get("entity_types_excluded", [])
                ],
                data_types_in_scope=scope_def_raw.get("data_types_in_scope", []),
                geographic_scope=scope_def_raw.get("geographic_scope"),
                sectoral_scope=scope_def_raw.get("sectoral_scope", []),
                material_scope=scope_def_raw.get("material_scope"),
                applicability_thresholds=[
                    ApplicabilityThreshold(
                        threshold_type=at["threshold_type"],
                        value=at["value"],
                        article_reference=at.get("article_reference"),
                    )
                    for at in scope_def_raw.get("applicability_thresholds", [])
                ],
            )

        return ExtractionSynthesis(
            component_registry=[
                ComponentEntry(
                    name=c["name"],
                    component_type=c.get("component_type", "unknown"),
                    evidence_refs=c.get("evidence_refs", []),
                    properties=c.get("properties"),
                )
                for c in result.get("component_registry", [])
            ],
            trust_boundaries=[
                TrustBoundaryCrossing(
                    source_domain=tb["source_domain"],
                    destination_domain=tb["destination_domain"],
                    data_transferred=tb.get("data_transferred", ""),
                    protocol_mechanism=tb.get("protocol_mechanism"),
                    components_involved=tb.get("components_involved", []),
                    evidence=tb.get("evidence"),
                )
                for tb in result.get("trust_boundaries", [])
            ],
            implicit_negatives=[
                ImplicitNegative(
                    missing_topic=neg["missing_topic"],
                    relevance_context=neg.get("relevance_context", ""),
                    related_topics_present=neg.get("related_topics_present", []),
                )
                for neg in result.get("implicit_negatives", [])
            ],
            ambiguities=[
                AmbiguityFlag(
                    vague_term=amb["vague_term"],
                    source_statement=amb.get("source_statement", ""),
                    section=amb.get("section"),
                    clarification_needed=amb.get("clarification_needed"),
                )
                for amb in result.get("ambiguities", [])
            ],
            analysis_context=analysis_context,
            obligation_registry=[
                ObligationEntry(
                    obligation_id=obl.get("obligation_id", f"OBL-{i+1:03d}"),
                    article_reference=obl["article_reference"],
                    obligation_text=obl.get("obligation_text", ""),
                    responsible_party=obl.get("responsible_party", ""),
                    action_required=obl.get("action_required", ""),
                    obligation_type=obl.get("obligation_type", "operational"),
                    deadline=obl.get("deadline"),
                    conditions=obl.get("conditions"),
                    exemptions=obl.get("exemptions"),
                    evidence=obl.get("evidence"),
                )
                for i, obl in enumerate(result.get("obligation_registry", []))
            ],
            deadline_inventory=[
                DeadlineEntry(
                    deadline_id=dl.get("deadline_id", f"DL-{i+1:03d}"),
                    requirement=dl.get("requirement", ""),
                    article_reference=dl["article_reference"],
                    duration=dl.get("duration", ""),
                    trigger_event=dl.get("trigger_event", ""),
                    deadline_type=dl.get("deadline_type", "implementation_deadline"),
                    responsible_party=dl.get("responsible_party"),
                    evidence=dl.get("evidence"),
                )
                for i, dl in enumerate(result.get("deadline_inventory", []))
            ],
            penalty_structures=[
                PenaltyEntry(
                    penalty_id=pen.get("penalty_id", f"PEN-{i+1:03d}"),
                    article_reference=pen["article_reference"],
                    violation_category=pen.get("violation_category", ""),
                    enforcement_body=pen.get("enforcement_body"),
                    max_fine_absolute=pen.get("max_fine_absolute"),
                    max_fine_revenue_based=pen.get("max_fine_revenue_based"),
                    calculation_method=pen.get("calculation_method"),
                    criminal_sanctions=pen.get("criminal_sanctions"),
                    administrative_measures=pen.get("administrative_measures", []),
                    aggravating_factors=pen.get("aggravating_factors", []),
                    mitigating_factors=pen.get("mitigating_factors", []),
                    private_right_of_action=pen.get("private_right_of_action", False),
                    evidence=pen.get("evidence"),
                )
                for i, pen in enumerate(result.get("penalty_structures", []))
            ],
            cross_regulation_references=[
                CrossRegulationReference(
                    reference_id=xref.get("reference_id", f"XREF-{i+1:03d}"),
                    source_article=xref.get("source_article", ""),
                    referenced_instrument=xref["referenced_instrument"],
                    reference_type=xref.get("reference_type", "complementary"),
                    relationship_description=xref.get("relationship_description", ""),
                    evidence=xref.get("evidence"),
                )
                for i, xref in enumerate(result.get("cross_regulation_references", []))
            ],
            scope_definitions=scope_definitions,
        )

    @staticmethod
    def _build_synthesis_input(
        truths: List[ExtractedTruth],
        entities: List[ExtractedEntity],
        relationships: List[ExtractedRelationship],
    ) -> str:
        """Format all extracted data as a structured text block for the synthesis prompt."""
        parts = []

        # Truths (usually the largest section)
        parts.append(f"TRUTHS ({len(truths)} total):")
        for i, t in enumerate(truths):
            doc_ref = f"Doc: {t.document_name}, " if t.document_name else ""
            citation = f"[{doc_ref}Section: {t.section}, Page: {t.page}, Para: {t.paragraph}]"
            parts.append(
                f"  T-{i+1}. [{t.statement_type.value.upper()}] {t.statement} "
                f"{citation} (confidence: {t.confidence}, entities: {t.entities})"
            )

        # Entities
        parts.append(f"\nENTITIES ({len(entities)} total):")
        for i, e in enumerate(entities):
            parts.append(f"  E-{i+1}. {e.name} ({e.entity_type}): {e.context}")

        # Relationships
        parts.append(f"\nRELATIONSHIPS ({len(relationships)} total):")
        for i, r in enumerate(relationships):
            flow_info = ""
            if r.source_component or r.destination_component:
                flow_info = (
                    f" | flow: {r.source_component or '?'} → "
                    f"{r.destination_component or '?'}"
                )
                if r.data_transferred:
                    flow_info += f" [{r.data_transferred}]"
                if r.protocol_mechanism:
                    flow_info += f" via {r.protocol_mechanism}"
            parts.append(
                f"  R-{i+1}. {r.entity_a} --[{r.relationship_type}]--> {r.entity_b} "
                f"(confidence: {r.confidence}){flow_info} | evidence: {r.evidence}"
            )

        return "\n".join(parts)

