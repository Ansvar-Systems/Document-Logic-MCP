"""Extraction schemas for LLM outputs.

Schema hierarchy:
- Pass 1: DocumentOverview (high-level document understanding)
- Pass 2: SectionExtraction (per-section truths, entities, relationships)
- Pass 3: ExtractionSynthesis (cross-section consolidation: component registry,
  trust boundaries, implicit negatives, ambiguity flags)

The synthesis pass (Pass 3) is optional and activated by passing an
`analysis_context` parameter (e.g., "stride_threat_modeling") to the extractor.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class StatementType(str, Enum):
    """Type of statement extracted."""
    ASSERTION = "assertion"
    PLAN = "plan"
    REQUIREMENT = "requirement"
    RECOMMENDATION = "recommendation"


class SourceAuthority(str, Enum):
    """Authority level of source document."""
    HIGH = "high"  # Official documentation, policies
    MEDIUM = "medium"  # Guidelines, procedures
    LOW = "low"  # Meeting notes, drafts


@dataclass
class ExtractedEntity:
    """Entity identified in document."""
    name: str
    entity_type: Optional[str]
    context: str


@dataclass
class ExtractedTruth:
    """Truth statement extracted from document."""
    statement: str
    section: str
    page: Optional[int]
    paragraph: Optional[int]
    statement_type: StatementType
    confidence: float
    entities: List[str]
    document_name: str = ""  # Source document filename, injected by extractor


@dataclass
class ExtractedRelationship:
    """Relationship between entities.

    Directional flow fields (source_component, destination_component, etc.)
    are populated when the relationship represents a data flow and the
    extraction prompt requests directionality (via analysis_context).
    """
    entity_a: str
    relationship_type: str
    entity_b: str
    evidence: str
    confidence: float
    # Directional flow fields (populated when analysis_context is set)
    source_component: Optional[str] = None
    destination_component: Optional[str] = None
    data_transferred: Optional[str] = None
    protocol_mechanism: Optional[str] = None


@dataclass
class DocumentOverview:
    """High-level document overview from Pass 1."""
    doc_id: str
    purpose: str
    topics: List[str]
    entities: List[ExtractedEntity]
    document_type: str


@dataclass
class SectionExtraction:
    """Extraction results from Pass 2."""
    section_title: str
    truths: List[ExtractedTruth]
    entities: List[ExtractedEntity]
    relationships: List[ExtractedRelationship]


@dataclass
class CrossReference:
    """Cross-reference link from Pass 3."""
    source_section: str
    target_section: str
    reference_type: str
    linked_entities: List[str]


# ─── Synthesis pass (Pass 3) schemas ──────────────────────────────────


@dataclass
class ComponentEntry:
    """Deduplicated component/asset in the component registry.

    Aggregates all mentions of a component across sections into a single
    entry with evidence references, enabling clean handoff to DFD generation.
    """
    name: str
    component_type: str  # e.g., "third_party_ai", "internal_service", "database"
    evidence_refs: List[str] = field(default_factory=list)  # truth IDs or citations
    properties: Optional[dict] = None  # version, vendor, protocol, etc.


@dataclass
class TrustBoundaryCrossing:
    """A point where data crosses between different trust domains.

    These are the seams where threats concentrate — identifying them
    explicitly saves downstream STRIDE analysis significant inference work.
    """
    source_domain: str       # e.g., "bank_internal_network"
    destination_domain: str  # e.g., "azure_cloud"
    data_transferred: str    # what crosses the boundary
    protocol_mechanism: Optional[str] = None  # e.g., "HTTPS/TLS 1.3"
    components_involved: List[str] = field(default_factory=list)
    evidence: Optional[str] = None


@dataclass
class ImplicitNegative:
    """A security-relevant topic conspicuously absent from the document.

    Contextual gap detection: only flags absences that are notable given
    what the document DOES cover. A data retention doc missing auth details
    is not notable; an auth flow doc missing session revocation IS.
    """
    missing_topic: str           # e.g., "session revocation"
    relevance_context: str       # why this absence is notable given document scope
    related_topics_present: List[str] = field(default_factory=list)  # what IS covered


@dataclass
class AmbiguityFlag:
    """Vague or underspecified security language that needs clarification.

    More aggressive than confidence scoring — explicitly calls out terms
    like "sanitized", "filtered", "secured" that lack mechanism specifics.
    """
    vague_term: str          # the ambiguous word/phrase
    source_statement: str    # the truth statement containing it
    section: Optional[str] = None
    clarification_needed: Optional[str] = None  # what specifically is unclear


@dataclass
class ExtractionSynthesis:
    """Cross-section consolidation output from Pass 3.

    Produced by running a synthesis LLM call over all extracted
    truths/entities/relationships. Activated by analysis_context parameter.
    """
    component_registry: List[ComponentEntry]
    trust_boundaries: List[TrustBoundaryCrossing]
    implicit_negatives: List[ImplicitNegative]
    ambiguities: List[AmbiguityFlag]
    analysis_context: str  # which context produced this synthesis
