"""Tests for LLM extraction."""

import pytest
from unittest.mock import Mock
from document_logic_mcp.extraction.extractor import DocumentExtractor
from document_logic_mcp.parsers.base import ParseResult, Section


@pytest.mark.asyncio
async def test_extract_document_overview():
    """Test extracting document overview."""
    # Mock LLM client
    mock_llm = Mock()
    mock_response = Mock()
    mock_response.content = [
        Mock(text='{"purpose": "Test doc", "topics": ["security"], "entities": [{"name": "AES-256", "entity_type": "technology", "context": "encryption"}], "document_type": "architecture"}')
    ]
    mock_llm.messages.create = Mock(return_value=mock_response)

    parse_result = ParseResult(
        filename="test.pdf",
        sections=[
            Section(title="Introduction", content="This system uses AES-256 encryption."),
        ],
        raw_text="This system uses AES-256 encryption.",
        page_count=1,
        metadata={}
    )

    extractor = DocumentExtractor(llm_client=mock_llm)
    overview = await extractor.extract_overview(parse_result)

    assert overview.doc_id is not None
    assert len(overview.entities) > 0
    assert overview.purpose == "Test doc"


@pytest.mark.asyncio
async def test_extract_document_overview_reconstructs_missing_raw_text():
    """Completed documents can still rebuild an overview from sections."""
    mock_llm = Mock()
    mock_response = Mock()
    mock_response.content = [
        Mock(text='{"purpose": "Nederlandse samenvatting", "topics": ["logging"], "entities": [{"name": "SIEM", "entity_type": "technology", "context": "centrale loggingoplossing"}], "document_type": "beleid"}')
    ]
    mock_llm.messages.create = Mock(return_value=mock_response)

    parse_result = ParseResult(
        filename="test.docx",
        sections=[
            Section(title="Logging", content="Alle productiegebeurtenissen worden centraal gelogd."),
        ],
        raw_text="Logging\nAlle productiegebeurtenissen worden centraal gelogd.",
        page_count=1,
        metadata={}
    )

    extractor = DocumentExtractor(llm_client=mock_llm)
    overview = await extractor.extract_overview(parse_result)

    assert overview.purpose == "Nederlandse samenvatting"
    assert overview.entities[0].context == "centrale loggingoplossing"
