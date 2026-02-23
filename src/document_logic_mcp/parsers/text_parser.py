"""Plain text and Markdown parser."""

import re
from pathlib import Path

from .base import BaseParser, ParseResult, Section


class TextParser(BaseParser):
    """Parser for .txt files."""

    def parse(self, file_path: Path) -> ParseResult:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        sections = self._detect_sections(lines)
        if not sections:
            sections = [Section(title="Document", content=text.strip())]

        return ParseResult(
            filename=file_path.name,
            sections=sections,
            raw_text=text,
            page_count=1,
            metadata={"parser": "text", "line_count": len(lines)},
        )

    def _detect_sections(self, lines: list[str]) -> list[Section]:
        """Try to detect sections from ALL-CAPS headers or numbered headings."""
        sections: list[Section] = []
        current_title: str | None = None
        current_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped and self._is_heading(stripped):
                if current_title is not None or current_lines:
                    sections.append(Section(
                        title=current_title or "Introduction",
                        content="\n".join(current_lines).strip(),
                    ))
                current_title = stripped
                current_lines = []
            else:
                current_lines.append(line)

        # Flush final section
        if current_title is not None or current_lines:
            sections.append(Section(
                title=current_title or "Document",
                content="\n".join(current_lines).strip(),
            ))

        # Only return detected sections if we found at least 2 headings
        if sum(1 for s in sections if s.title not in ("Introduction", "Document")) >= 2:
            return sections
        return []

    @staticmethod
    def _is_heading(line: str) -> bool:
        words = line.split()
        if len(words) <= 8 and line == line.upper() and line != line.lower():
            return True
        if re.match(r"^\d+(?:\.\d+)*\s+\S", line) and len(line) < 120 and "," not in line:
            return True
        return False


class MarkdownParser(BaseParser):
    """Parser for .md files — uses heading structure."""

    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)")

    def parse(self, file_path: Path) -> ParseResult:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        sections = self._parse_headings(text)

        if not sections:
            # Fall back to TextParser logic
            fallback = TextParser()
            return fallback.parse(file_path)

        return ParseResult(
            filename=file_path.name,
            sections=sections,
            raw_text=text,
            page_count=1,
            metadata={"parser": "markdown", "section_count": len(sections)},
        )

    def _parse_headings(self, text: str) -> list[Section]:
        sections: list[Section] = []
        current_title: str | None = None
        current_lines: list[str] = []

        for line in text.splitlines():
            m = self._HEADING_RE.match(line)
            if m:
                if current_title is not None or current_lines:
                    sections.append(Section(
                        title=current_title or "Introduction",
                        content="\n".join(current_lines).strip(),
                    ))
                current_title = m.group(2).strip()
                current_lines = []
            else:
                current_lines.append(line)

        if current_title is not None or current_lines:
            sections.append(Section(
                title=current_title or "Document",
                content="\n".join(current_lines).strip(),
            ))

        # Only use heading-based sections if we found actual headings
        if sum(1 for s in sections if s.title not in ("Introduction", "Document")) >= 1:
            return sections
        return []
