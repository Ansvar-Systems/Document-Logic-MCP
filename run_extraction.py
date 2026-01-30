#!/usr/bin/env python3
"""Run extraction on tough document with existing doc_id."""

import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from document_logic_mcp.tools import extract_document_tool
from document_logic_mcp.export import AssessmentExporter
from document_logic_mcp.database import Database


async def main():
    """Run extraction on already-parsed document."""
    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY environment variable not set")
        print()
        print("Please set your API key:")
        print("  export ANTHROPIC_API_KEY='your-key-here'")
        print()
        print("Or run with:")
        print("  ANTHROPIC_API_KEY='your-key' python run_extraction.py")
        sys.exit(1)

    doc_id = "517d4718-ae72-47d9-9c5d-07a94568b177"
    db_path = Path("data/tough_test.db")

    print("=" * 80)
    print("RUNNING EXTRACTION WITH SECTION-BY-SECTION PROCESSING")
    print("=" * 80)
    print()
    print(f"Document ID: {doc_id}")
    print(f"Database: {db_path}")
    print()

    # Verify sections are stored
    db = Database(db_path)
    async with db.connection() as conn:
        cursor = await conn.execute(
            "SELECT COUNT(*) as count FROM sections WHERE doc_id = ?",
            (doc_id,)
        )
        row = await cursor.fetchone()
        section_count = row["count"]

    print(f"Sections in database: {section_count}")
    print()

    if section_count == 0:
        print("ERROR: No sections found. Run verify_section_storage.py first.")
        sys.exit(1)

    # Run extraction
    print("Starting extraction (this will take a few minutes)...")
    print()

    try:
        result = await extract_document_tool(doc_id, db_path)

        print()
        print("=" * 80)
        print("EXTRACTION COMPLETE")
        print("=" * 80)
        print()
        print(f"Status: {result['status']}")
        print(f"Truths extracted: {result['truths_extracted']}")
        print(f"Entities found: {result['entities_found']}")
        print(f"Relationships: {result['relationships_found']}")
        print()

        # Export results
        print("Exporting results to markdown...")
        exporter = AssessmentExporter(db)
        output_path = Path("docs/tough_document_fixed_extraction.md")
        await exporter.export_markdown(output_path)
        print(f"✓ Exported to: {output_path}")
        print()

        # Compare to target
        print("=" * 80)
        print("RESULTS ANALYSIS")
        print("=" * 80)
        print(f"Before fix: 24 truths (sections 1-3 only)")
        print(f"After fix:  {result['truths_extracted']} truths (all {section_count} sections)")
        print(f"Target:     60-80+ truths")
        print()

        if result['truths_extracted'] >= 60:
            print("✅ SUCCESS: Comprehensive extraction achieved!")
            print("   Section-by-section processing is working correctly.")
        elif result['truths_extracted'] >= 40:
            print("⚠️  IMPROVEMENT: Better than before, but under target")
            print("   May need prompt tuning or more aggressive extraction.")
        else:
            print("❌ ISSUE: Still under-extracting")
            print("   Need to investigate extraction prompts.")

    except Exception as e:
        print(f"ERROR: Extraction failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
