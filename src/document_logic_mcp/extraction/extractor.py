"""Document extraction using LLM."""

import logging
import json
import uuid
from typing import Optional
from anthropic import Anthropic
from .prompts import OVERVIEW_PROMPT, SECTION_EXTRACTION_PROMPT
from .schemas import (
    DocumentOverview,
    SectionExtraction,
    ExtractedEntity,
    ExtractedTruth,
    ExtractedRelationship,
    StatementType,
)
from ..parsers.base import ParseResult

logger = logging.getLogger(__name__)


class DocumentExtractor:
    """Extract structured information from parsed documents."""

    def __init__(self, llm_client: Optional[Anthropic] = None):
        """Initialize extractor with LLM client."""
        self.llm = llm_client or Anthropic()

    async def extract_overview(self, parse_result: ParseResult) -> DocumentOverview:
        """Pass 1: Extract high-level document overview."""
        prompt = OVERVIEW_PROMPT.format(
            filename=parse_result.filename,
            text=parse_result.raw_text[:50000]  # Limit to ~50k chars for context
        )

        response = self.llm.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        result = json.loads(response.content[0].text)

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
        page: Optional[int] = None
    ) -> SectionExtraction:
        """Pass 2: Extract truths, entities, relationships from section."""
        prompt = SECTION_EXTRACTION_PROMPT.format(
            filename=filename,
            doc_purpose=doc_context.purpose,
            doc_type=doc_context.document_type,
            section_title=section_title,
            section_content=section_content[:30000]  # Limit section size
        )

        response = self.llm.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}]
        )

        result = json.loads(response.content[0].text)

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
                ExtractedRelationship(**r) for r in result["relationships"]
            ]
        )
