"""Data models for Document Logic MCP."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class DocumentMetadata:
    """Metadata about a processed document."""

    doc_id: str
    filename: str
    document_date: Optional[str]  # Date from document content
    upload_date: datetime
    sections_count: int
    status: str  # "parsed", "extracted", "complete"


@dataclass
class Truth:
    """A factual statement extracted from a document."""

    truth_id: str
    doc_id: str
    statement: str
    source_section: str
    source_page: Optional[int]
    statement_type: str  # "fact", "opinion", "definition", "instruction"
    confidence: float  # 0.0 to 1.0
    source_authority: str  # "primary", "secondary", "tertiary"
    related_entities: list[str]  # Entity IDs


@dataclass
class Entity:
    """A named entity mentioned in documents."""

    entity_id: str
    entity_name: str
    doc_id: str
    first_mention_section: str
    first_mention_page: Optional[int]
    entity_type: str  # "person", "organization", "location", "date", "other"
    mention_count: int


@dataclass
class EntityAlias:
    """Relationship indicating two entities are the same."""

    entity_a_id: str
    entity_b_id: str
    confidence: float  # 0.0 to 1.0
    evidence: str  # Description of why they're the same
    relationship_type: str  # "alias", "abbreviation", "variation"


@dataclass
class Relationship:
    """A relationship between two entities."""

    relationship_id: str
    entity_a_id: str
    relationship_type: str
    entity_b_id: str
    source_section: str
    source_page: Optional[int]
    confidence: float  # 0.0 to 1.0
