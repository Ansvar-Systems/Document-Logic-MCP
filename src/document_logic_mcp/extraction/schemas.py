"""Extraction schemas for LLM outputs."""

from dataclasses import dataclass
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


@dataclass
class ExtractedRelationship:
    """Relationship between entities."""
    entity_a: str
    relationship_type: str
    entity_b: str
    evidence: str
    confidence: float


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
