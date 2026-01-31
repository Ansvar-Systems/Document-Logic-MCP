"""JSON document parser for structured vendor profiles."""

import json
import logging
from pathlib import Path
from typing import List
from .base import BaseParser, ParseResult, Section

logger = logging.getLogger(__name__)


class JSONParser(BaseParser):
    """Parser for JSON vendor profile documents."""

    def parse(self, file_path: Path) -> ParseResult:
        """Parse JSON document and return structured result.

        For JSON vendor documents, the data is already structured.
        We convert top-level keys into sections for consistency with
        the Document-Logic MCP data model.
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        sections: List[Section] = []
        raw_text_parts: List[str] = []

        # Strategy: Convert top-level JSON keys into sections
        for key, value in data.items():
            # Format section content as JSON for readability
            if isinstance(value, (dict, list)):
                content = json.dumps(value, indent=2, ensure_ascii=False)
            else:
                content = str(value)

            sections.append(Section(
                title=key.replace('_', ' ').title(),
                content=content,
                page_start=None,
                page_end=None
            ))

            # Build raw text representation
            raw_text_parts.append(f"{key}: {content}")

        raw_text = "\n\n".join(raw_text_parts)

        # Extract metadata (vendor name, service type if available)
        metadata = {}
        if "vendor_name" in data:
            metadata["vendor_name"] = data["vendor_name"]
        if "vendor_information" in data and isinstance(data["vendor_information"], dict):
            vendor_info = data["vendor_information"]
            if "company_name" in vendor_info:
                metadata["vendor_name"] = vendor_info["company_name"]
            if "industry" in vendor_info:
                metadata["industry"] = vendor_info["industry"]

        logger.info(f"Parsed JSON document: {file_path.name} ({len(sections)} sections)")

        return ParseResult(
            filename=file_path.name,
            sections=sections,
            raw_text=raw_text,
            page_count=1,  # JSON is single "page"
            metadata=metadata
        )
