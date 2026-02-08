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

                if not content:
                    # Content is None or empty - log the full response for debugging
                    finish_reason = choices[0].get("finish_reason", "unknown")
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

        # Nothing worked - log what we got and raise
        preview = stripped[:200] if len(stripped) > 200 else stripped
        raise ValueError(
            f"Could not extract valid JSON from LLM response. "
            f"Response preview: {preview!r}"
        )

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
                    entities=t["entities"]
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
            citation = f"[Section: {t.section}, Page: {t.page}, Para: {t.paragraph}]"
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

