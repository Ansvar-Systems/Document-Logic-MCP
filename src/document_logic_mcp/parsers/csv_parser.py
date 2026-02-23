"""CSV parser."""

import csv
import io
from pathlib import Path

from .base import BaseParser, ParseResult, Section

# Group rows into chunks of this size when the file is large
_CHUNK_SIZE = 20


class CSVParser(BaseParser):
    """Parser for .csv files."""

    def parse(self, file_path: Path) -> ParseResult:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = reader.fieldnames or []
        rows = list(reader)

        if not rows:
            return ParseResult(
                filename=file_path.name,
                sections=[Section(title="Empty CSV", content="No data rows found.")],
                raw_text=text,
                page_count=1,
                metadata={"parser": "csv", "column_count": len(fieldnames), "row_count": 0},
            )

        key_col = fieldnames[0] if fieldnames else None

        if len(rows) <= 100:
            sections = self._row_sections(rows, key_col)
        else:
            sections = self._chunked_sections(rows, key_col)

        return ParseResult(
            filename=file_path.name,
            sections=sections,
            raw_text=text,
            page_count=1,
            metadata={
                "parser": "csv",
                "column_count": len(fieldnames),
                "row_count": len(rows),
                "columns": list(fieldnames),
            },
        )

    @staticmethod
    def _row_to_text(row: dict) -> str:
        return "\n".join(f"{k}: {v}" for k, v in row.items() if v)

    def _row_sections(self, rows: list[dict], key_col: str | None) -> list[Section]:
        sections: list[Section] = []
        for idx, row in enumerate(rows, start=1):
            label = row.get(key_col, "") if key_col else ""
            title = f"Row {idx}" + (f" — {label}" if label else "")
            sections.append(Section(title=title, content=self._row_to_text(row)))
        return sections

    def _chunked_sections(self, rows: list[dict], key_col: str | None) -> list[Section]:
        sections: list[Section] = []
        for start in range(0, len(rows), _CHUNK_SIZE):
            chunk = rows[start : start + _CHUNK_SIZE]
            end = start + len(chunk)
            title = f"Rows {start + 1}–{end}"
            content = "\n\n".join(
                f"--- Row {start + i + 1} ---\n{self._row_to_text(r)}"
                for i, r in enumerate(chunk)
            )
            sections.append(Section(title=title, content=content))
        return sections
