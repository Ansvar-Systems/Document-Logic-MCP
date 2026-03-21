"""Stateless extraction pipeline.

Pure async function that accepts pre-parsed sections and returns extracted
results accumulated in memory. No SQLite writes; no side effects.

Schema mapping (internal dataclass → output dict):
    ExtractedTruth.section       → source_section
    ExtractedTruth.page          → source_page
    ExtractedTruth.paragraph     → (dropped)
    ExtractedTruth.entities      → (dropped)
    ExtractedTruth.document_name → (dropped)
    ExtractedEntity.name         → name
    ExtractedEntity.entity_type  → entity_type
    ExtractedEntity.context      → (dropped)
    (none)                       → mention_count (default 1, summed on dedup)
    (none)                       → properties (empty {})
    ExtractedRelationship.entity_a          → source_entity
    ExtractedRelationship.entity_b          → target_entity
    ExtractedRelationship.relationship_type → relationship
    ExtractedRelationship.evidence          → (dropped)
    (none)                                  → source_section (from section context)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .extractor import DocumentExtractor

from ..parsers.base import ParseResult, Section
from .schemas import (
    DocumentOverview,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractedTruth,
)

logger = logging.getLogger(__name__)

VERSION = "2.0.0"


@dataclass
class ExtractionInput:
    """Input to the stateless extraction pipeline."""

    sections: list  # list of dicts with at least "title" and "content" keys
    filename: str
    analysis_context: Optional[str]
    input_hash: str
    schema_version: str


@dataclass
class ExtractionOutput:
    """Output from the stateless extraction pipeline."""

    truths: list  # list of spec-aligned dicts
    entities: list  # list of spec-aligned dicts (deduplicated)
    relationships: list  # list of spec-aligned dicts
    overview: Optional[str]  # DocumentOverview.purpose, or None on failure
    synthesis: Optional[Any]  # serialisable synthesis dict, or None
    metadata: dict  # envelope: schema_version, extractor_version, model_used, etc.


# ─── Field mapping helpers ───────────────────────────────────────────────────


def _map_truth(truth: ExtractedTruth, source_section: str) -> dict:
    return {
        "statement": truth.statement,
        "source_section": source_section,
        "source_page": truth.page,
        "statement_type": truth.statement_type.value if hasattr(truth.statement_type, "value") else truth.statement_type,
        "confidence": truth.confidence,
    }


def _map_entity(entity: ExtractedEntity, source_section: str) -> dict:
    return {
        "name": entity.name,
        "entity_type": entity.entity_type,
        "mention_count": 1,
        "properties": {},
        "source_section": source_section,
    }


def _map_relationship(rel: ExtractedRelationship, source_section: str) -> dict:
    out = {
        "source_entity": rel.entity_a,
        "target_entity": rel.entity_b,
        "relationship": rel.relationship_type,
        "confidence": rel.confidence,
        "source_section": source_section,
    }
    # Preserve directional flow fields when present
    if rel.source_component is not None:
        out["source_component"] = rel.source_component
    if rel.destination_component is not None:
        out["destination_component"] = rel.destination_component
    if rel.data_transferred is not None:
        out["data_transferred"] = rel.data_transferred
    if rel.protocol_mechanism is not None:
        out["protocol_mechanism"] = rel.protocol_mechanism
    return out


# ─── Entity deduplication ────────────────────────────────────────────────────


def _dedup_entities(entity_dicts: list) -> list:
    """Collapse exact name+type duplicates, summing mention_count."""
    seen: dict[tuple, dict] = {}
    for ent in entity_dicts:
        key = (ent["name"], ent.get("entity_type"))
        if key in seen:
            seen[key]["mention_count"] += ent.get("mention_count", 1)
        else:
            seen[key] = dict(ent)
    return list(seen.values())


# ─── Synthesis serialisation (mirrors tools.py pattern) ─────────────────────


def _serialise_synthesis(synthesis) -> dict:
    """Convert ExtractionSynthesis dataclass to a serialisable dict."""
    out: dict = {
        "analysis_context": synthesis.analysis_context,
        "component_registry": [
            {
                "name": c.name,
                "component_type": c.component_type,
                "evidence_refs": c.evidence_refs,
                "properties": c.properties,
            }
            for c in synthesis.component_registry
        ],
        "trust_boundaries": [
            {
                "source_domain": tb.source_domain,
                "destination_domain": tb.destination_domain,
                "data_transferred": tb.data_transferred,
                "protocol_mechanism": tb.protocol_mechanism,
                "components_involved": tb.components_involved,
                "evidence": tb.evidence,
            }
            for tb in synthesis.trust_boundaries
        ],
        "implicit_negatives": [
            {
                "missing_topic": neg.missing_topic,
                "relevance_context": neg.relevance_context,
                "related_topics_present": neg.related_topics_present,
            }
            for neg in synthesis.implicit_negatives
        ],
        "ambiguities": [
            {
                "vague_term": amb.vague_term,
                "source_statement": amb.source_statement,
                "section": amb.section,
                "clarification_needed": amb.clarification_needed,
            }
            for amb in synthesis.ambiguities
        ],
    }

    if synthesis.obligation_registry:
        out["obligation_registry"] = [
            {
                "obligation_id": obl.obligation_id,
                "article_reference": obl.article_reference,
                "obligation_text": obl.obligation_text,
                "responsible_party": obl.responsible_party,
                "action_required": obl.action_required,
                "obligation_type": obl.obligation_type,
                "deadline": obl.deadline,
                "conditions": obl.conditions,
                "exemptions": obl.exemptions,
                "evidence": obl.evidence,
            }
            for obl in synthesis.obligation_registry
        ]

    if synthesis.deadline_inventory:
        out["deadline_inventory"] = [
            {
                "deadline_id": dl.deadline_id,
                "requirement": dl.requirement,
                "article_reference": dl.article_reference,
                "duration": dl.duration,
                "trigger_event": dl.trigger_event,
                "deadline_type": dl.deadline_type,
                "responsible_party": dl.responsible_party,
                "evidence": dl.evidence,
            }
            for dl in synthesis.deadline_inventory
        ]

    if synthesis.penalty_structures:
        out["penalty_structures"] = [
            {
                "penalty_id": pen.penalty_id,
                "article_reference": pen.article_reference,
                "violation_category": pen.violation_category,
                "enforcement_body": pen.enforcement_body,
                "max_fine_absolute": pen.max_fine_absolute,
                "max_fine_revenue_based": pen.max_fine_revenue_based,
                "calculation_method": pen.calculation_method,
                "criminal_sanctions": pen.criminal_sanctions,
                "administrative_measures": pen.administrative_measures,
                "aggravating_factors": pen.aggravating_factors,
                "mitigating_factors": pen.mitigating_factors,
                "private_right_of_action": pen.private_right_of_action,
                "evidence": pen.evidence,
            }
            for pen in synthesis.penalty_structures
        ]

    if synthesis.cross_regulation_references:
        out["cross_regulation_references"] = [
            {
                "reference_id": xref.reference_id,
                "source_article": xref.source_article,
                "referenced_instrument": xref.referenced_instrument,
                "reference_type": xref.reference_type,
                "relationship_description": xref.relationship_description,
                "evidence": xref.evidence,
            }
            for xref in synthesis.cross_regulation_references
        ]

    if synthesis.scope_definitions:
        sd = synthesis.scope_definitions
        out["scope_definitions"] = {
            "entity_types_included": [
                {
                    "entity_type": et.entity_type,
                    "description": et.description,
                    "article_reference": et.article_reference,
                    "evidence": et.evidence,
                }
                for et in sd.entity_types_included
            ],
            "entity_types_excluded": [
                {
                    "entity_type": et.entity_type,
                    "description": et.description,
                    "article_reference": et.article_reference,
                    "evidence": et.evidence,
                }
                for et in sd.entity_types_excluded
            ],
            "data_types_in_scope": sd.data_types_in_scope,
            "geographic_scope": sd.geographic_scope,
            "sectoral_scope": sd.sectoral_scope,
            "material_scope": sd.material_scope,
            "applicability_thresholds": [
                {
                    "threshold_type": at.threshold_type,
                    "value": at.value,
                    "article_reference": at.article_reference,
                }
                for at in sd.applicability_thresholds
            ],
        }

    return out


# ─── Main pipeline function ──────────────────────────────────────────────────


async def run_extraction(inp: ExtractionInput, extractor: "DocumentExtractor") -> ExtractionOutput:
    """Run the three-pass extraction pipeline in memory and return results.

    Pass 1 — overview: builds DocumentOverview from the full document.
    Pass 2 — sections: extracts truths/entities/relationships per section.
              Failed sections are skipped (non-fatal); a warning is recorded.
    Pass 3 — synthesis: runs cross-section consolidation when analysis_context
              is set. Failure is non-fatal.

    Args:
        inp: ExtractionInput with pre-parsed sections and metadata.
        extractor: DocumentExtractor instance.

    Returns:
        ExtractionOutput with spec-aligned dicts and a metadata envelope.
    """
    start = time.monotonic()
    warnings: list[str] = []

    # Build a ParseResult so extract_overview can use .raw_text
    sections_obj = [
        Section(
            title=s.get("title", ""),
            content=s.get("content", ""),
            page_start=s.get("page_start"),
            page_end=s.get("page_end"),
        )
        for s in inp.sections
    ]
    raw_text = "\n\n".join(
        f"{s.title}\n{s.content}" for s in sections_obj
    )
    parse_result = ParseResult(
        filename=inp.filename,
        sections=sections_obj,
        raw_text=raw_text,
        page_count=max((s.page_start or 0 for s in sections_obj), default=0),
        metadata={},
    )

    # ── Pass 1: overview ──────────────────────────────────────────────────
    logger.info("Pass 1: Extracting document overview for '%s'", inp.filename)
    try:
        overview: DocumentOverview = await extractor.extract_overview(parse_result)
    except Exception as e:
        msg = f"Overview extraction failed: {e}"
        logger.warning(msg)
        warnings.append(msg)
        overview = DocumentOverview(
            doc_id="stateless",
            purpose="",
            topics=[],
            entities=[],
            document_type="unknown",
        )

    # ── Pass 2: per-section extraction ────────────────────────────────────
    logger.info("Pass 2: Extracting from %d sections", len(inp.sections))

    truth_dicts: list[dict] = []
    entity_dicts: list[dict] = []
    relationship_dicts: list[dict] = []

    # Also collect raw dataclass instances for Pass 3
    all_truths: list[ExtractedTruth] = []
    all_entities: list[ExtractedEntity] = []
    all_relationships: list[ExtractedRelationship] = []

    failed_sections: list[str] = []

    for idx, section_obj in enumerate(sections_obj):
        section_title = section_obj.title
        logger.info(
            "  Section %d/%d: %s", idx + 1, len(inp.sections), section_title
        )
        try:
            result = await extractor.extract_section(
                section_title=section_title,
                section_content=section_obj.content,
                doc_context=overview,
                filename=inp.filename,
                page=section_obj.page_start,
                analysis_context=inp.analysis_context,
            )
        except Exception as exc:
            msg = f"Section '{section_title}' failed: {type(exc).__name__}: {exc}"
            logger.warning(msg)
            warnings.append(msg)
            failed_sections.append(section_title)
            continue

        # Map to spec-aligned dicts
        for truth in result.truths:
            truth_dicts.append(_map_truth(truth, section_title))
        for entity in result.entities:
            entity_dicts.append(_map_entity(entity, section_title))
        for rel in result.relationships:
            relationship_dicts.append(_map_relationship(rel, section_title))

        # Accumulate raw instances for synthesis
        all_truths.extend(result.truths)
        all_entities.extend(result.entities)
        all_relationships.extend(result.relationships)

    if failed_sections:
        logger.warning(
            "%d/%d sections failed: %s",
            len(failed_sections), len(inp.sections), failed_sections,
        )

    # Dedup entities by name+type
    deduped_entities = _dedup_entities(entity_dicts)

    # ── Pass 3: synthesis (only when analysis_context is set) ─────────────
    synthesis_output = None
    if inp.analysis_context:
        logger.info(
            "Pass 3: Synthesis for analysis_context='%s'", inp.analysis_context
        )
        try:
            synthesis = await extractor.synthesize(
                filename=inp.filename,
                doc_context=overview,
                all_truths=all_truths,
                all_entities=all_entities,
                all_relationships=all_relationships,
                section_count=len(inp.sections),
                analysis_context=inp.analysis_context,
            )
            if synthesis is not None:
                synthesis_output = _serialise_synthesis(synthesis)
        except Exception as exc:
            msg = f"Synthesis failed (non-fatal): {type(exc).__name__}: {exc}"
            logger.error(msg, exc_info=True)
            warnings.append(msg)
            synthesis_output = {
                "error": msg,
                "analysis_context": inp.analysis_context,
            }

    duration = time.monotonic() - start

    metadata = {
        "schema_version": inp.schema_version,
        "extractor_version": VERSION,
        "model_used": getattr(extractor, "extraction_model", None),
        "input_hash": inp.input_hash,
        "section_count": len(inp.sections),
        "truths_count": len(truth_dicts),
        "entities_count": len(deduped_entities),
        "relationships_count": len(relationship_dicts),
        "duration_seconds": round(duration, 3),
        "warnings": warnings,
    }

    logger.info(
        "extraction_complete",
        extra={
            "section_count": len(inp.sections),
            "truths_count": len(truth_dicts),
            "entities_count": len(deduped_entities),
            "relationships_count": len(relationship_dicts),
            "duration_seconds": round(duration, 2),
            "model_used": getattr(extractor, "extraction_model", None) or "unknown",
            "warnings_count": len(warnings),
        },
    )

    return ExtractionOutput(
        truths=truth_dicts,
        entities=deduped_entities,
        relationships=relationship_dicts,
        overview=overview.purpose if overview else None,
        synthesis=synthesis_output,
        metadata=metadata,
    )
