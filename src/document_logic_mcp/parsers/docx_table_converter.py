"""Convert DOCX tables to Markdown format for reliable LLM extraction."""

import logging
from typing import List
from docx.table import Table

logger = logging.getLogger(__name__)


def table_to_markdown(table: Table) -> str:
    """Convert a python-docx Table object to Markdown format.

    LLMs parse Markdown tables reliably without additional prompting,
    making this conversion more robust than passing raw cell text.

    Args:
        table: python-docx Table object

    Returns:
        Markdown-formatted table string

    Example:
        Input table:
        | Name    | Location | Status |
        | AWS     | US       | Active |
        | Datadog | US       | Active |

        Output:
        | Name | Location | Status |
        |------|----------|--------|
        | AWS | US | Active |
        | Datadog | US | Active |
    """
    if not table.rows:
        return ""

    rows = []
    for row in table.rows:
        cells = [cell.text.strip().replace('\n', ' ').replace('|', '\\|') for cell in row.cells]
        rows.append(cells)

    if not rows:
        return ""

    # Determine column count from first row
    col_count = len(rows[0])

    # Build Markdown table
    markdown_lines = []

    # Header row (first row)
    markdown_lines.append('| ' + ' | '.join(rows[0]) + ' |')

    # Separator row
    markdown_lines.append('|' + '|'.join(['---' for _ in range(col_count)]) + '|')

    # Data rows
    for row in rows[1:]:
        # Pad row to match column count if needed
        padded_row = row + [''] * (col_count - len(row))
        markdown_lines.append('| ' + ' | '.join(padded_row[:col_count]) + ' |')

    return '\n'.join(markdown_lines)


def extract_tables_as_markdown(doc) -> List[tuple[int, str]]:
    """Extract all tables from a docx Document and convert to Markdown.

    Returns a list of (paragraph_index, markdown_table) tuples indicating
    where each table appears in the document flow.

    Args:
        doc: python-docx Document object

    Returns:
        List of (position, markdown_string) tuples
    """
    tables_with_positions = []

    # python-docx doesn't provide paragraph index for tables directly,
    # so we need to track position by iterating through the document XML
    #
    # For now, we'll use a simpler approach: extract all tables and
    # insert them at reasonable positions in the text flow

    for table_idx, table in enumerate(doc.tables):
        markdown = table_to_markdown(table)
        if markdown:
            # Estimate position: distribute tables evenly through document
            # More sophisticated: scan XML for table positions
            estimated_position = (table_idx + 1) * 100  # Placeholder
            tables_with_positions.append((estimated_position, markdown))

            logger.info(
                f"Converted table {table_idx + 1}/{len(doc.tables)}: "
                f"{len(table.rows)} rows, {len(table.columns)} columns"
            )

    return tables_with_positions


def get_table_paragraph_positions(doc) -> List[int]:
    """Get the paragraph index where each table appears.

    Scans the document XML to find exactly where tables are positioned
    relative to paragraphs, enabling accurate insertion in text flow.

    Args:
        doc: python-docx Document object

    Returns:
        List of paragraph indices (0-based) where tables appear
    """
    # Access the document body XML
    body = doc._element.body
    table_positions = []
    paragraph_count = 0

    # Iterate through body children (paragraphs and tables)
    for child in body:
        # Check if it's a table element
        if child.tag.endswith('}tbl'):
            # Table found at this position (after paragraph_count paragraphs)
            table_positions.append(paragraph_count)
        elif child.tag.endswith('}p'):
            # It's a paragraph
            paragraph_count += 1

    return table_positions
