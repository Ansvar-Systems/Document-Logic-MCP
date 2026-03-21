"""Tests for stateless extraction pipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from document_logic_mcp.extraction.pipeline import (
    ExtractionInput,
    ExtractionOutput,
    run_extraction,
    VERSION,
)
from document_logic_mcp.extraction.schemas import (
    DocumentOverview,
    SectionExtraction,
    ExtractedTruth,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionSynthesis,
    ComponentEntry,
    TrustBoundaryCrossing,
    ImplicitNegative,
    AmbiguityFlag,
    StatementType,
)


def _make_overview():
    return DocumentOverview(
        doc_id="test-doc-id",
        purpose="Test document purpose",
        topics=["security", "architecture"],
        entities=[
            ExtractedEntity(name="TestSystem", entity_type="service", context="core service")
        ],
        document_type="architecture",
    )


def _make_section_extraction(section_title, entity_name="EntityA"):
    return SectionExtraction(
        section_title=section_title,
        truths=[
            ExtractedTruth(
                statement="The system uses TLS 1.3.",
                section=section_title,
                page=1,
                paragraph=None,
                statement_type=StatementType.ASSERTION,
                confidence=0.9,
                entities=[entity_name],
                document_name="test.pdf",
            )
        ],
        entities=[
            ExtractedEntity(
                name=entity_name,
                entity_type="technology",
                context="encryption",
            )
        ],
        relationships=[
            ExtractedRelationship(
                entity_a=entity_name,
                relationship_type="uses",
                entity_b="TLS",
                evidence="Section text",
                confidence=0.85,
            )
        ],
    )


def _make_extractor(overview=None, section_extraction=None):
    extractor = MagicMock()
    extractor.extraction_model = "test-model"
    extractor.extract_overview = AsyncMock(return_value=overview or _make_overview())
    extractor.extract_section = AsyncMock(
        return_value=section_extraction or _make_section_extraction("Section 1")
    )
    extractor.synthesize = AsyncMock(return_value=None)
    return extractor


@pytest.mark.asyncio
async def test_run_extraction_returns_complete_payload():
    """Two sections produce truths, entities, relationships and a valid metadata envelope."""
    extractor = _make_extractor()
    # Return different section extractions per call
    extractor.extract_section = AsyncMock(
        side_effect=[
            _make_section_extraction("Section 1", "EntityA"),
            _make_section_extraction("Section 2", "EntityB"),
        ]
    )

    inp = ExtractionInput(
        sections=[
            {"title": "Section 1", "content": "Content one.", "page_start": 1},
            {"title": "Section 2", "content": "Content two.", "page_start": 2},
        ],
        filename="test.pdf",
        analysis_context=None,
        input_hash="abc123",
        schema_version="1.0",
    )

    result = await run_extraction(inp, extractor)

    assert isinstance(result, ExtractionOutput)
    assert len(result.truths) == 2
    # Each section has 1 entity; EntityA and EntityB are distinct → 2 entities
    assert len(result.entities) == 2
    assert len(result.relationships) == 2

    # Spec-aligned field names in truths
    assert "source_section" in result.truths[0]
    assert "source_page" in result.truths[0]
    assert "paragraph" not in result.truths[0]
    assert "document_name" not in result.truths[0]

    # Spec-aligned field names in entities
    assert "name" in result.entities[0]
    assert "entity_type" in result.entities[0]
    assert "mention_count" in result.entities[0]
    assert "properties" in result.entities[0]
    assert result.entities[0]["properties"] == {}
    assert "context" not in result.entities[0]

    # Spec-aligned field names in relationships
    assert "source_entity" in result.relationships[0]
    assert "target_entity" in result.relationships[0]
    assert "relationship" in result.relationships[0]
    assert "evidence" not in result.relationships[0]

    # Metadata envelope
    meta = result.metadata
    assert meta["schema_version"] == "1.0"
    assert meta["input_hash"] == "abc123"
    assert meta["counts"]["truths"] == 2
    assert meta["counts"]["entities"] == 2
    assert meta["counts"]["relationships"] == 2
    assert "duration_seconds" in meta
    assert "model_used" in meta
    assert "extractor_version" in meta
    assert isinstance(meta["warnings"], list)

    assert result.synthesis is None


@pytest.mark.asyncio
async def test_run_extraction_deduplicates_entities():
    """Same entity name+type from two sections is collapsed into one with summed mention_count."""
    extractor = _make_extractor()
    extractor.extract_section = AsyncMock(
        side_effect=[
            _make_section_extraction("Section 1", "SharedEntity"),
            _make_section_extraction("Section 2", "SharedEntity"),
        ]
    )

    inp = ExtractionInput(
        sections=[
            {"title": "Section 1", "content": "Content one."},
            {"title": "Section 2", "content": "Content two."},
        ],
        filename="test.pdf",
        analysis_context=None,
        input_hash="dedup123",
        schema_version="1.0",
    )

    result = await run_extraction(inp, extractor)

    # Both sections produce "SharedEntity" (same name + type) → collapse to 1
    assert len(result.entities) == 1
    assert result.entities[0]["name"] == "SharedEntity"
    assert result.entities[0]["mention_count"] == 2


@pytest.mark.asyncio
async def test_run_extraction_skips_failed_sections():
    """One section failure is non-fatal; successful sections are returned and warning recorded."""
    extractor = _make_extractor()
    extractor.extract_section = AsyncMock(
        side_effect=[
            RuntimeError("LLM timeout"),
            _make_section_extraction("Section 2"),
        ]
    )

    inp = ExtractionInput(
        sections=[
            {"title": "Section 1", "content": "Content one."},
            {"title": "Section 2", "content": "Content two."},
        ],
        filename="test.pdf",
        analysis_context=None,
        input_hash="fail123",
        schema_version="1.0",
    )

    result = await run_extraction(inp, extractor)

    # Only the successful section's data is in the output
    assert len(result.truths) == 1
    assert result.truths[0]["source_section"] == "Section 2"

    # Warning must be recorded
    assert len(result.metadata["warnings"]) >= 1
    assert any("Section 1" in w for w in result.metadata["warnings"])
