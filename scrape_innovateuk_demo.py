"""
Demo script showing end-to-end scraping pipeline.

Usage:
    python -m src.scripts.scrape_innovateuk_demo
"""

import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.ingest.innovateuk_competition import InnovateUKCompetitionScraper
from src.ingest.resource_ingestor import ResourceIngestor


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


# Test URLs
TEST_URLS = [
    "https://apply-for-innovation-funding.service.gov.uk/competition/2341/overview/4b0efce9-75b8-4e84-97c0-fc6277396586",
    # Add more test URLs here
]


def main():
    """Run scraping demo."""
    print("=" * 80)
    print("INNOVATE UK COMPETITION SCRAPER - DEMO")
    print("=" * 80)
    print()

    # Initialize scrapers
    comp_scraper = InnovateUKCompetitionScraper()
    resource_ingestor = ResourceIngestor()

    for url in TEST_URLS:
        print(f"\n{'=' * 80}")
        print(f"Scraping: {url}")
        print(f"{'=' * 80}\n")

        try:
            # Scrape competition
            result = comp_scraper.scrape_competition(url)

            # Print competition metadata
            print("=== COMPETITION METADATA ===")
            print(f"ID: {result.competition.id}")
            print(f"External ID: {result.competition.external_id}")
            print(f"Title: {result.competition.title}")
            print(f"Opens: {result.competition.opens_at}")
            print(f"Closes: {result.competition.closes_at}")
            print(f"Total Fund: {result.competition.total_fund}")
            print(f"Project Size: {result.competition.project_size}")
            print(f"Funding Rules: {result.competition.funding_rules}")
            if result.competition.description:
                desc = result.competition.description
                print(f"Description: {desc[:200]}..." if len(desc) > 200 else f"Description: {desc}")

            # Print sections
            print(f"\n=== SECTIONS ({len(result.sections)}) ===")
            for section in result.sections:
                print(f"  - {section.name:25} | {section.url:80} | {len(section.text):6} chars")

            # Print resources
            print(f"\n=== RESOURCES ({len(result.resources)}) ===")
            for res in result.resources:
                scope_marker = "🎯" if res.scope.value == "competition" else "🌍"
                type_marker = {"pdf": "📄", "video": "🎥", "webpage": "🌐"}.get(res.type.value, "❓")
                comp_id = res.competition_id or "GLOBAL"
                print(f"  {scope_marker} {type_marker} [{comp_id:15}] {res.title or res.url}")

            # Fetch documents from resources
            print(f"\n=== FETCHING DOCUMENTS ===")
            docs = resource_ingestor.fetch_documents_for_resources(result.resources)

            print(f"\n=== DOCUMENTS ({len(docs)}) ===")
            for doc in docs:
                comp_id = doc.competition_id or "GLOBAL"
                print(f"  - {doc.doc_type:15} | {comp_id:15} | {len(doc.text):7} chars | {doc.source_url}")

            # Document type breakdown
            print(f"\n{'=' * 80}")
            print("DOCUMENT TYPE BREAKDOWN")
            print(f"{'=' * 80}")

            pdf_docs = [d for d in docs if d.doc_type == "briefing_pdf"]
            guidance_docs = [d for d in docs if d.doc_type == "guidance"]

            print(f"\nPDFs: {len(pdf_docs)}")
            for doc in pdf_docs:
                title = next((r.title for r in result.resources if r.id == doc.resource_id), "Unknown")
                print(f"  - {title} ({len(doc.text)} chars)")

            print(f"\nGuidance pages: {len(guidance_docs)}")
            for doc in guidance_docs[:5]:  # Show first 5
                title = next((r.title for r in result.resources if r.id == doc.resource_id), "Unknown")
                print(f"  - {title} ({len(doc.text)} chars)")

            # Assertion
            if len(pdf_docs) > 0:
                print(f"\n✓ PDF detection working correctly")
            else:
                print(f"\n✗ Warning: No PDFs detected (expected at least 1)")

            # Summary
            print(f"\n{'=' * 80}")
            print("SUMMARY")
            print(f"{'=' * 80}")
            print(f"Competition: {result.competition.title}")
            print(f"Sections: {len(result.sections)}")
            print(f"Resources: {len(result.resources)}")
            print(f"  - Competition-specific: {sum(1 for r in result.resources if r.competition_id)}")
            print(f"  - Global: {sum(1 for r in result.resources if not r.competition_id)}")
            print(f"Documents: {len(docs)}")
            print(f"  - PDFs: {sum(1 for d in docs if d.doc_type == 'briefing_pdf')}")
            print(f"  - Guidance pages: {sum(1 for d in docs if d.doc_type == 'guidance')}")

            # Detailed resource breakdown
            print(f"\n{'=' * 80}")
            print("DETAILED RESOURCE BREAKDOWN")
            print(f"{'=' * 80}")

            # Group by scope
            global_resources = [r for r in result.resources if r.scope.value == "global"]
            comp_resources = [r for r in result.resources if r.scope.value == "competition"]

            print(f"\nGLOBAL RESOURCES ({len(global_resources)}):")
            for r in global_resources[:10]:  # Show first 10
                print(f"  - [{r.type.value:8}] {r.title or r.url[:60]}")
            if len(global_resources) > 10:
                print(f"  ... and {len(global_resources) - 10} more")

            print(f"\nCOMPETITION RESOURCES ({len(comp_resources)}):")
            for r in comp_resources:
                print(f"  - [{r.type.value:8}] {r.title or r.url[:60]}")

            # Validation checks
            print(f"\n{'=' * 80}")
            print("VALIDATION CHECKS")
            print(f"{'=' * 80}")

            # Check sections
            expected_sections = ["summary", "eligibility", "scope", "dates", "how-to-apply", "supporting-information"]
            found_sections = [s.name for s in result.sections]

            for expected in expected_sections:
                if expected in found_sections:
                    print(f"✓ Section '{expected}' found")
                else:
                    print(f"✗ Section '{expected}' MISSING")

            # Check resources
            if len(result.resources) >= 10:
                print(f"✓ Resource extraction working (found {len(result.resources)} resources)")
                print(f"  - Competition-specific: {sum(1 for r in result.resources if r.scope.value == 'competition')}")
                print(f"  - Global: {sum(1 for r in result.resources if r.scope.value == 'global')}")
            else:
                print(f"✗ Expected at least 10 resources, got {len(result.resources)}")

            # Check for common Innovate UK guidance links
            expected_keywords = [
                "project setup",
                "bank details",
                "mandatory checks",
                "applicants receive",
            ]

            print(f"\nExpected resource topics:")
            for keyword in expected_keywords:
                if any(keyword.lower() in (r.title or "").lower() for r in result.resources):
                    print(f"✓ Found resource about: {keyword}")
                else:
                    print(f"✗ Missing resource about: {keyword}")

            print()

        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'=' * 80}")
    print("DEMO COMPLETE")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
