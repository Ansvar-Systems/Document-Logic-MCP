"""DOCX document parser using python-docx."""

import logging
from pathlib import Path
from docx import Document
from .base import BaseParser, ParseResult, Section

logger = logging.getLogger(__name__)


class DOCXParser(BaseParser):
    """Parser for DOCX documents."""

    def parse(self, file_path: Path) -> ParseResult:
        """Parse DOCX document."""
        doc = Document(file_path)

        sections = []
        raw_text = []
        current_section_title = None
        current_section_content = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            raw_text.append(text)

            # Detect headings by style (handle missing styles gracefully)
            is_heading = False
            if para.style and para.style.name and para.style.name.startswith('Heading'):
                is_heading = True

            if is_heading:
                # Save previous section
                if current_section_title:
                    sections.append(Section(
                        title=current_section_title,
                        content='\n'.join(current_section_content)
                    ))
                current_section_title = text
                current_section_content = []
            else:
                current_section_content.append(text)

        # Save last section
        if current_section_title:
            sections.append(Section(
                title=current_section_title,
                content='\n'.join(current_section_content)
            ))

        # If no sections detected, treat whole document as one section
        if not sections:
            sections.append(Section(
                title="Document",
                content='\n'.join(raw_text)
            ))

        return ParseResult(
            filename=file_path.name,
            sections=sections,
            raw_text='\n'.join(raw_text),
            page_count=len(doc.sections),
            metadata={
                "parser": "python-docx",
                "paragraph_count": len(doc.paragraphs),
            }
        )
