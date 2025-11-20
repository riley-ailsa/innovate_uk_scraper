"""
End-to-end pipeline for backfilling Innovate UK competitions.

Usage:
    python -m src.scripts.backfill_innovate_uk_competitions

This script demonstrates the complete flow:
1. Scrape raw competition data
2. Fetch supporting documents
3. Normalize to canonical domain models
4. (Future) Write to GrantStore and VectorIndex
"""

import sys
import logging
from pathlib import Path
from typing import List

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.ingest.innovateuk_competition import InnovateUKCompetitionScraper
from src.ingest.resource_ingestor import ResourceIngestor
from src.normalize.innovate_uk import normalize_scraped_competition


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Test URLs
TEST_URLS = [
    "https://apply-for-innovation-funding.service.gov.uk/competition/2341/overview/4b0efce9-75b8-4e84-97c0-fc6277396586",
    # Add more URLs here as needed
]


def backfill_competitions(urls: List[str]):
    """
    Run end-to-end backfill for a list of competition URLs.

    Args:
        urls: List of Innovate UK competition URLs
    """
    logger.info(f"Starting backfill for {len(urls)} competitions")

    # Initialize scrapers
    comp_scraper = InnovateUKCompetitionScraper()
    resource_ingestor = ResourceIngestor()

    # Track results
    grants = []
    all_indexable_docs = []

    for i, url in enumerate(urls, 1):
        logger.info(f"\n{'=' * 80}")
        logger.info(f"[{i}/{len(urls)}] Processing: {url}")
        logger.info(f"{'=' * 80}\n")

        try:
            # Step 1: Scrape competition
            logger.info("Step 1: Scraping competition metadata and sections...")
            scraped = comp_scraper.scrape_competition(url)
            logger.info(f"✓ Scraped: {scraped.competition.title}")
            logger.info(f"  - Sections: {len(scraped.sections)}")
            logger.info(f"  - Resources: {len(scraped.resources)}")

            # Step 2: Fetch documents
            logger.info("\nStep 2: Fetching and parsing documents...")
            documents = resource_ingestor.fetch_documents_for_resources(scraped.resources)
            logger.info(f"✓ Fetched {len(documents)} documents")
            logger.info(f"  - PDFs: {sum(1 for d in documents if d.doc_type == 'briefing_pdf')}")
            logger.info(f"  - Guidance: {sum(1 for d in documents if d.doc_type == 'guidance')}")

            # Step 3: Normalize to canonical models
            logger.info("\nStep 3: Normalizing to canonical domain models...")
            grant, indexable_docs = normalize_scraped_competition(scraped, documents)
            logger.info(f"✓ Normalized to Grant: {grant.id}")
            logger.info(f"  - Active: {grant.is_active}")
            logger.info(f"  - Tags: {', '.join(grant.tags)}")
            logger.info(f"  - Indexable docs: {len(indexable_docs)}")

            # Track results
            grants.append(grant)
            all_indexable_docs.extend(indexable_docs)

            # Display sample indexable docs
            logger.info("\nSample indexable documents:")
            for doc in indexable_docs[:5]:
                logger.info(f"  - [{doc.doc_type:25}] {doc.citation_text}")
                logger.info(f"    Text preview: {doc.text[:100]}...")

            logger.info(f"\n✓ Successfully processed: {grant.title}\n")

        except Exception as e:
            logger.error(f"✗ Error processing {url}: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Summary
    logger.info(f"\n{'=' * 80}")
    logger.info("BACKFILL SUMMARY")
    logger.info(f"{'=' * 80}")
    logger.info(f"Competitions processed: {len(grants)}/{len(urls)}")
    logger.info(f"Total indexable documents: {len(all_indexable_docs)}")
    logger.info(f"Active grants: {sum(1 for g in grants if g.is_active)}")
    logger.info(f"Inactive grants: {sum(1 for g in grants if not g.is_active)}")

    # Document type breakdown
    logger.info("\nIndexable document breakdown:")
    doc_types = {}
    for doc in all_indexable_docs:
        doc_types[doc.doc_type] = doc_types.get(doc.doc_type, 0) + 1

    for doc_type, count in sorted(doc_types.items()):
        logger.info(f"  - {doc_type:25}: {count:3} documents")

    logger.info("\n" + "=" * 80)
    logger.info("NEXT STEPS")
    logger.info("=" * 80)
    logger.info("✓ Scraping: COMPLETE")
    logger.info("✓ Document fetching: COMPLETE")
    logger.info("✓ Normalization: COMPLETE")
    logger.info("⏳ TODO: Implement GrantStore (database layer)")
    logger.info("⏳ TODO: Implement VectorIndex (chunking + embeddings)")
    logger.info("⏳ TODO: Implement search API (query → results + citations)")

    return grants, all_indexable_docs


def main():
    """Run backfill pipeline."""
    print("=" * 80)
    print("INNOVATE UK BACKFILL PIPELINE")
    print("=" * 80)
    print()

    grants, indexable_docs = backfill_competitions(TEST_URLS)

    print("\n" + "=" * 80)
    print("PIPELINE COMPLETE")
    print("=" * 80)
    print(f"Grants: {len(grants)}")
    print(f"Indexable documents: {len(indexable_docs)}")
    print()


if __name__ == "__main__":
    main()
