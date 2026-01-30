#!/usr/bin/env python3
"""Verify section storage works correctly (no API key needed)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from document_logic_mcp.tools import parse_document_tool
from document_logic_mcp.database import Database


async def main():
    """Verify sections are stored correctly."""
    doc_path = "/Users/jeffreyvonrotz/Downloads/tough_test_document.docx"
    db_path = Path("data/tough_test.db")

    print("=" * 80)
    print("VERIFYING SECTION STORAGE FIX")
    print("=" * 80)
    print()

    # Parse document
    print("Step 1: Parsing document...")
    parse_result = await parse_document_tool(doc_path, db_path)
    print(f"  ✓ Sections found during parsing: {parse_result['sections_count']}")
    doc_id = parse_result['doc_id']
    print(f"  ✓ Document ID: {doc_id}")
    print()

    # Verify sections were stored in database
    print("Step 2: Verifying sections stored in database...")
    db = Database(db_path)

    async with db.connection() as conn:
        cursor = await conn.execute(
            "SELECT section_id, title, section_index FROM sections WHERE doc_id = ? ORDER BY section_index",
            (doc_id,)
        )
        section_rows = await cursor.fetchall()

    print(f"  ✓ Sections in database: {len(section_rows)}")
    print()

    if len(section_rows) == parse_result['sections_count']:
        print("✅ SUCCESS: All sections stored correctly!")
        print()
        print("Sections stored:")
        for row in section_rows:
            print(f"  {row['section_index'] + 1}. {row['title']}")
        print()
        print("=" * 80)
        print("NEXT STEP: Run extraction through MCP server")
        print("=" * 80)
        print()
        print("The parsing fix is working. To complete the test:")
        print("1. Use the MCP server tools (which have API key access)")
        print(f"2. Call extract_document with doc_id: {doc_id}")
        print("3. Verify 60-80+ truths are extracted")
        print()
        print("Or set ANTHROPIC_API_KEY and run:")
        print("  python test_tough_document_fixed.py")
    else:
        print(f"❌ FAILURE: Expected {parse_result['sections_count']} sections, found {len(section_rows)}")


if __name__ == "__main__":
    asyncio.run(main())
