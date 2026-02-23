"""HTML parser."""

import re
from pathlib import Path

from .base import BaseParser, ParseResult, Section

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_STRIP_TAGS = {"script", "style", "nav", "footer", "header"}


class HTMLParser(BaseParser):
    """Parser for .html / .htm files using BeautifulSoup."""

    def parse(self, file_path: Path) -> ParseResult:
        from bs4 import BeautifulSoup

        raw = file_path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(raw, "html.parser")

        # Extract title
        title_tag = soup.find("title")
        doc_title = title_tag.get_text(strip=True) if title_tag else file_path.stem

        # Remove non-content elements
        for tag in soup.find_all(_STRIP_TAGS):
            tag.decompose()

        sections = self._heading_sections(soup)
        if not sections:
            sections = self._paragraph_sections(soup)
        if not sections:
            text = self._normalize(soup.get_text())
            sections = [Section(title=doc_title, content=text)]

        raw_text = self._normalize(soup.get_text())

        return ParseResult(
            filename=file_path.name,
            sections=sections,
            raw_text=raw_text,
            page_count=1,
            metadata={"parser": "beautifulsoup", "title": doc_title},
        )

    def _heading_sections(self, soup) -> list[Section]:
        """Split content by <h1>–<h6> tags."""
        headings = soup.find_all(_HEADING_TAGS)
        if not headings:
            return []

        sections: list[Section] = []
        for i, heading in enumerate(headings):
            title = heading.get_text(strip=True)
            # Collect siblings until next heading
            content_parts: list[str] = []
            for sibling in heading.next_siblings:
                if getattr(sibling, "name", None) in _HEADING_TAGS:
                    break
                text = sibling.get_text(strip=True) if hasattr(sibling, "get_text") else str(sibling).strip()
                if text:
                    content_parts.append(text)
            sections.append(Section(title=title, content="\n".join(content_parts)))

        return sections

    def _paragraph_sections(self, soup) -> list[Section]:
        """Fallback: treat <p> blocks as sections."""
        paragraphs = soup.find_all("p")
        if len(paragraphs) < 2:
            return []

        sections: list[Section] = []
        for i, p in enumerate(paragraphs, start=1):
            text = p.get_text(strip=True)
            if text:
                preview = text[:60] + "..." if len(text) > 60 else text
                sections.append(Section(title=f"Paragraph {i}: {preview}", content=text))
        return sections

    @staticmethod
    def _normalize(text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()
