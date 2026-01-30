"""PDF document parser using pdfplumber."""

import logging
from pathlib import Path
import pdfplumber
from .base import BaseParser, ParseResult, Section

logger = logging.getLogger(__name__)


class PDFParser(BaseParser):
    """Parser for PDF documents."""

    def parse(self, file_path: Path) -> ParseResult:
        """Parse PDF document."""
        sections = []
        raw_text = []

        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)

            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                raw_text.append(text)

                # Simple section detection: look for headings (all caps lines)
                lines = text.split('\n')
                current_section_title = None
                current_section_content = []

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Heuristic: if line is short and all caps, it's a heading
                    if len(line) < 100 and line.isupper() and len(line.split()) <= 8:
                        # Save previous section
                        if current_section_title:
                            sections.append(Section(
                                title=current_section_title,
                                content='\n'.join(current_section_content),
                                page_start=page_num,
                                page_end=page_num
                            ))
                        current_section_title = line
                        current_section_content = []
                    else:
                        current_section_content.append(line)

                # Save last section of page
                if current_section_title:
                    sections.append(Section(
                        title=current_section_title,
                        content='\n'.join(current_section_content),
                        page_start=page_num,
                        page_end=page_num
                    ))

            # If no sections detected, treat whole document as one section
            if not sections:
                sections.append(Section(
                    title="Document",
                    content='\n'.join(raw_text),
                    page_start=1,
                    page_end=page_count
                ))

            return ParseResult(
                filename=file_path.name,
                sections=sections,
                raw_text='\n'.join(raw_text),
                page_count=page_count,
                metadata={
                    "parser": "pdfplumber",
                    "page_count": page_count,
                }
            )
