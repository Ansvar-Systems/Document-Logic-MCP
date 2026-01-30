#!/usr/bin/env python3
"""Test tough document extraction with section-by-section processing."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from document_logic_mcp.tools import parse_document_tool, extract_document_tool
from document_logic_mcp.export import AssessmentExporter
from document_logic_mcp.database import Database


async def main():
    """Run tough document test."""
    doc_path = "/Users/jeffreyvonrotz/Downloads/tough_test_document.docx"
    db_path = Path("data/tough_test.db")

    print("=" * 80)
    print("TOUGH DOCUMENT TEST - SECTION-BY-SECTION EXTRACTION")
    print("=" * 80)
    print()

    # Step 1: Parse
    print("Step 1: Parsing document...")
    parse_result = await parse_document_tool(doc_path, db_path)
    print(f"  ✓ Parsed: {parse_result['sections_count']} sections found")
    print(f"  Document ID: {parse_result['doc_id']}")
    print()

    doc_id = parse_result['doc_id']

    # Step 2: Extract
    print("Step 2: Extracting truths from all sections...")
    extract_result = await extract_document_tool(doc_id, db_path)
    print(f"  ✓ Extracted: {extract_result['truths_extracted']} truths")
    print(f"  ✓ Entities: {extract_result['entities_found']}")
    print(f"  ✓ Relationships: {extract_result['relationships_found']}")
    print()

    # Step 3: Export
    print("Step 3: Exporting results...")
    db = Database(db_path)
    exporter = AssessmentExporter(db)
    await exporter.export_markdown(Path("docs/tough_document_output_fixed.md"))
    print(f"  ✓ Exported to: docs/tough_document_output_fixed.md")
    print()

    print("=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)
    print(f"Sections processed: {parse_result['sections_count']}")
    print(f"Truths extracted: {extract_result['truths_extracted']}")
    print(f"Target: 60-80+ truths")
    print()

    if extract_result['truths_extracted'] >= 60:
        print("✅ SUCCESS: Comprehensive extraction achieved!")
    elif extract_result['truths_extracted'] >= 40:
        print("⚠️  PARTIAL: Better than before, but still under target")
    else:
        print("❌ FAILURE: Still under-extracting")

    print()


if __name__ == "__main__":
    asyncio.run(main())
