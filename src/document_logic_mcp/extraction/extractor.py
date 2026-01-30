"""Document extraction using LLM.

This module supports two modes:
1. Direct Anthropic API (legacy - requires ANTHROPIC_API_KEY)
2. LLM Gateway (recommended - uses configured extraction model)

Set LLM_GATEWAY_URL environment variable to use gateway mode.
"""

import logging
import json
import uuid
import os
from typing import Optional
import httpx
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
    """Extract structured information from parsed documents.

    Supports two modes:
    - Gateway mode: Uses LLM Gateway (set LLM_GATEWAY_URL)
    - Direct mode: Uses Anthropic API directly (set ANTHROPIC_API_KEY)
    """

    def __init__(self, llm_client: Optional[Anthropic] = None):
        """Initialize extractor with LLM client or gateway.

        Args:
            llm_client: Optional Anthropic client (for direct mode only)
        """
        self.gateway_url = os.getenv("LLM_GATEWAY_URL")
        self.gateway_token = os.getenv("LLM_GATEWAY_API_KEY", "dev")
        self.extraction_model = os.getenv("EXTRACTION_MODEL", "claude-sonnet-4-20250514")

        if self.gateway_url:
            logger.info(f"Using LLM Gateway mode: {self.gateway_url}, model: {self.extraction_model}")
            self.llm = None
        else:
            logger.info("Using Direct Anthropic API mode")
            self.llm = llm_client or Anthropic()

    async def _call_llm(self, prompt: str, max_tokens: int = 4096) -> str:
        """Call LLM via gateway or direct API.

        Args:
            prompt: The prompt to send
            max_tokens: Maximum tokens in response

        Returns:
            LLM response text
        """
        if self.gateway_url:
            # Gateway mode - call LLM Gateway with service API key
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    f"{self.gateway_url}/api/v1/chat/completions",
                    headers={
                        "X-Service-API-Key": self.gateway_token,
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.extraction_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens
                    }
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        else:
            # Direct Anthropic API mode
            response = self.llm.messages.create(
                model=self.extraction_model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text

    async def extract_overview(self, parse_result: ParseResult) -> DocumentOverview:
        """Pass 1: Extract high-level document overview."""
        prompt = OVERVIEW_PROMPT.format(
            filename=parse_result.filename,
            text=parse_result.raw_text[:50000]  # Limit to ~50k chars for context
        )

        response_text = await self._call_llm(prompt, max_tokens=4096)
        result = json.loads(response_text)

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

        response_text = await self._call_llm(prompt, max_tokens=8192)
        result = json.loads(response_text)

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
