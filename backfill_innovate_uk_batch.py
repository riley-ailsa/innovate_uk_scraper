"""
Batch ingestion script for Innovate UK competitions.

Reads URLs from innovate_uk_links.txt and:
1. Scrapes each competition
2. Normalizes to domain objects
3. Persists to database
4. Indexes for search

Usage:
    python -m src.scripts.backfill_innovate_uk_batch
"""

import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.ingest.innovateuk_competition import InnovateUKCompetitionScraper
from src.ingest.resource_ingestor import ResourceIngestor
from src.normalize.innovate_uk import normalize_scraped_competition
from src.storage.grant_store import GrantStore
from src.storage.document_store import DocumentStore
from src.index.vector_index import VectorIndex


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Configuration
LINKS_FILE = "innovate_uk_links.txt"
DB_PATH = "grants.db"
SAMPLE_LIMIT = 10  # Process first N competitions (remove for full ingestion)


def load_links(path: str) -> list:
    """
    Load competition URLs from text file.

    Args:
        path: Path to links file

    Returns:
        List of URLs
    """
    file_path = Path(path)

    if not file_path.exists():
        logger.error(f"Links file not found: {path}")
        logger.info("Create innovate_uk_links.txt with one URL per line")
        return []

    with file_path.open() as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    logger.info(f"Loaded {len(urls)} URLs from {path}")
    return urls


def main():
    """Run the batch ingestion pipeline."""
    logger.info("=" * 80)
    logger.info("INNOVATE UK BATCH INGESTION PIPELINE")
    logger.info("=" * 80)

    # Load URLs
    urls = load_links(LINKS_FILE)

    if not urls:
        logger.error("No URLs to process")
        return

    # Limit to sample for initial runs
    if SAMPLE_LIMIT:
        logger.info(f"Processing first {SAMPLE_LIMIT} competitions (SAMPLE MODE)")
        urls = urls[:SAMPLE_LIMIT]

    # Initialize components
    logger.info("Initializing components...")
    scraper = InnovateUKCompetitionScraper()
    ingestor = ResourceIngestor()
    grant_store = GrantStore(DB_PATH)
    doc_store = DocumentStore(DB_PATH)
    vector_index = VectorIndex()

    # Track global content hashes for de-duplication
    existing_hashes = set()

    # Statistics
    stats = {
        "processed": 0,
        "skipped": 0,
        "failed": 0,
        "total_documents": 0,
    }

    # Process each URL
    for i, url in enumerate(urls, 1):
        logger.info(f"\n{'=' * 80}")
        logger.info(f"[{i}/{len(urls)}] Processing: {url}")
        logger.info(f"{'=' * 80}")

        # Skip if already ingested
        if grant_store.exists_by_url(url):
            logger.info(f"⏭️  Skipping (already ingested): {url}")
            stats["skipped"] += 1
            continue

        try:
            # Step 1: Scrape
            logger.info("Step 1: Scraping...")
            scraped = scraper.scrape_competition(url)
            logger.info(f"  ✓ Sections: {len(scraped.sections)}")
            logger.info(f"  ✓ Resources: {len(scraped.resources)}")

            # Step 2: Ingest resources
            logger.info("Step 2: Ingesting resources...")
            resource_docs = ingestor.fetch_documents_for_resources(
                scraped.resources,
                existing_hashes=existing_hashes,
            )
            logger.info(f"  ✓ Documents: {len(resource_docs)}")

            # Step 3: Normalize
            logger.info("Step 3: Normalizing...")
            grant, indexable_docs = normalize_scraped_competition(
                scraped,
                resource_docs,
            )
            logger.info(f"  ✓ Grant: {grant.id} - {grant.title}")
            logger.info(f"  ✓ Indexable docs: {len(indexable_docs)}")

            # Step 4: Persist to database
            logger.info("Step 4: Persisting to database...")
            grant_store.upsert_grant(grant)
            doc_store.upsert_documents(indexable_docs)
            logger.info(f"  ✓ Saved to database")

            # Step 5: Index for search
            logger.info("Step 5: Indexing for search...")
            vector_index.index_documents(indexable_docs)
            logger.info(f"  ✓ Indexed")

            # Update stats
            stats["processed"] += 1
            stats["total_documents"] += len(indexable_docs)

            logger.info(f"✅ Successfully processed: {grant.title}")

        except Exception as e:
            logger.exception(f"❌ Failed to process {url}: {e}")
            stats["failed"] += 1

    # Final summary
    logger.info(f"\n{'=' * 80}")
    logger.info("PIPELINE COMPLETE")
    logger.info(f"{'=' * 80}")
    logger.info(f"Processed:       {stats['processed']}")
    logger.info(f"Skipped:         {stats['skipped']}")
    logger.info(f"Failed:          {stats['failed']}")
    logger.info(f"Total documents: {stats['total_documents']}")
    logger.info(f"Database:        {DB_PATH}")
    logger.info(f"{'=' * 80}")

    if SAMPLE_LIMIT:
        logger.info("\n⚠️  SAMPLE MODE: Only processed first {} competitions".format(SAMPLE_LIMIT))
        logger.info("Remove SAMPLE_LIMIT in script to process all URLs")


if __name__ == "__main__":
    main()
