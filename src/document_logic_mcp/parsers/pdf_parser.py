"""PDF document parser using pdfplumber with OCR fallback for scanned pages."""

import logging
import re
from pathlib import Path
from .base import BaseParser, ParseResult, Section

logger = logging.getLogger(__name__)

# Minimum non-whitespace characters per page before triggering OCR fallback.
# Pages with fewer characters than this are considered "scanned" / image-only.
_OCR_THRESHOLD = 50

# Numbered heading patterns (same as DOCX parser — shared heuristic).
_NUMBERED_HEADING_PATTERNS = [
    (re.compile(r'^\d+\.\d+\.\d+\s+[A-Z]\w'), 3),
    (re.compile(r'^\d+\.\d+\s+[A-Z]\w'), 2),
    (re.compile(r'^\d+\.\s+[A-Z]\w'), 1),
]
_MAX_HEADING_LENGTH = 120
_LIST_ITEM_CHARS = re.compile(r'[,;]')
_NUMBER_PREFIX_RE = re.compile(r'^\d+(?:\.\d+)*\.?\s+(.*)')

# Sentence-start words that indicate body text, not headings.
_SENTENCE_STARTERS = frozenset({
    'The', 'This', 'These', 'Those', 'That',
    'A', 'An', 'Each', 'Every', 'All',
    'It', 'Its', 'Our', 'We', 'They',
    'When', 'If', 'For', 'In', 'On', 'At',
    'There', 'Here', 'Any', 'Some', 'No',
    'Most', 'Many', 'Several',
})


def _is_heading(line: str) -> bool:
    """Detect if a line is a heading using multiple heuristics.

    1. ALL CAPS, short, few words (original heuristic)
    2. Numbered heading pattern with four-layer rejection:
       length, comma/semicolon, sentence starters, uppercase start
    """
    if not line or len(line) >= _MAX_HEADING_LENGTH:
        return False

    # Heuristic 1: ALL CAPS heading (original)
    if line.isupper() and len(line.split()) <= 8:
        return True

    # Heuristic 2: Numbered heading pattern
    if _LIST_ITEM_CHARS.search(line):
        return False

    # Reject sentences: "1. The system validates tokens..."
    m = _NUMBER_PREFIX_RE.match(line)
    if m:
        rest = m.group(1)
        words = rest.split()
        if words and words[0] in _SENTENCE_STARTERS:
            return False

    for pattern, _level in _NUMBERED_HEADING_PATTERNS:
        if pattern.match(line):
            return True

    return False


class PDFParser(BaseParser):
    """Parser for PDF documents with OCR fallback for scanned pages."""

    def parse(self, file_path: Path) -> ParseResult:
        """Parse PDF document. Falls back to OCR for scanned/image-only pages."""
        import pdfplumber

        sections = []
        raw_text = []
        ocr_pages = 0

        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)

            # First pass: extract text from all pages, identify scanned pages
            page_texts: list[tuple[int, str]] = []
            scanned_page_nums: list[int] = []

            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                non_ws = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
                if non_ws < _OCR_THRESHOLD:
                    scanned_page_nums.append(page_num)
                page_texts.append((page_num, text))

            # OCR scanned pages if any were detected
            ocr_results: dict[int, str] = {}
            if scanned_page_nums:
                ocr_results = self._ocr_pages(file_path, scanned_page_nums)
                ocr_pages = len([p for p in scanned_page_nums if ocr_results.get(p, "").strip()])

            # Build sections using best text per page
            for page_num, text in page_texts:
                if page_num in ocr_results and ocr_results[page_num].strip():
                    text = ocr_results[page_num]

                raw_text.append(text)

                lines = text.split('\n')
                current_section_title = None
                current_section_content = []

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    if _is_heading(line):
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

            parser_name = "pdfplumber"
            if ocr_pages:
                parser_name = f"pdfplumber+ocr({ocr_pages}/{page_count} pages)"
                logger.info(
                    f"OCR applied to {ocr_pages}/{page_count} scanned pages in {file_path.name}"
                )

            return ParseResult(
                filename=file_path.name,
                sections=sections,
                raw_text='\n'.join(raw_text),
                page_count=page_count,
                metadata={
                    "parser": parser_name,
                    "page_count": page_count,
                    "ocr_pages": ocr_pages,
                }
            )

    @staticmethod
    def _ocr_pages(file_path: Path, page_nums: list[int]) -> dict[int, str]:
        """OCR specific pages of a PDF using pdf2image + pytesseract."""
        try:
            from pdf2image import convert_from_path
            import pytesseract
        except ImportError as e:
            logger.warning(f"OCR dependencies not available, skipping scanned pages: {e}")
            return {}

        results: dict[int, str] = {}
        for page_num in page_nums:
            try:
                images = convert_from_path(
                    file_path,
                    first_page=page_num,
                    last_page=page_num,
                    dpi=300,
                )
                if images:
                    text = pytesseract.image_to_string(images[0])
                    results[page_num] = text.strip()
            except Exception as e:
                logger.warning(f"OCR failed for page {page_num} of {file_path.name}: {e}")

        return results
