"""
Production-ready batch ingestion for Innovate UK competitions.

Features:
- Batch processing with configurable size
- Rate limiting to avoid overwhelming servers
- Checkpoint/resume capability
- Comprehensive error handling
- Progress tracking
- Duplicate detection

Usage:
    python src/scripts/backfill_innovate_uk_production.py \
        --input innovate_uk_links.txt \
        --batch-size 25 \
        --delay 1.5
"""

import sys
import time
import random
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Set

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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backfill.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BatchIngestor:
    """
    Production-ready batch ingestor with checkpointing and rate limiting.
    """

    def __init__(
        self,
        db_path: str = "grants.db",
        checkpoint_file: str = "processed_urls.txt",
        batch_size: int = 25,
        min_delay: float = 1.0,
        max_delay: float = 2.0,
    ):
        """
        Initialize batch ingestor.

        Args:
            db_path: Database path
            checkpoint_file: File to track processed URLs
            batch_size: URLs to process per batch
            min_delay: Minimum delay between requests (seconds)
            max_delay: Maximum delay between requests (seconds)
        """
        self.db_path = db_path
        self.checkpoint_file = Path(checkpoint_file)
        self.batch_size = batch_size
        self.min_delay = min_delay
        self.max_delay = max_delay

        # Initialize components
        self.scraper = InnovateUKCompetitionScraper()
        self.ingestor = ResourceIngestor()
        self.grant_store = GrantStore(db_path)
        self.doc_store = DocumentStore(db_path)
        self.vector_index = VectorIndex(db_path=db_path)

        # Track progress
        self.processed_urls = self._load_checkpoint()
        self.existing_hashes: Set[str] = set()

        # Statistics
        self.stats = {
            "total": 0,
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "total_documents": 0,
        }

    def _load_checkpoint(self) -> Set[str]:
        """Load set of already processed URLs."""
        if not self.checkpoint_file.exists():
            return set()

        with self.checkpoint_file.open() as f:
            urls = {line.strip() for line in f if line.strip()}

        logger.info(f"Loaded {len(urls)} processed URLs from checkpoint")
        return urls

    def _save_checkpoint(self, url: str):
        """Save URL to checkpoint file."""
        with self.checkpoint_file.open("a") as f:
            f.write(f"{url}\n")

    def load_urls(self, filepath: str) -> list:
        """
        Load URLs from file.

        Args:
            filepath: Path to text file with URLs

        Returns:
            List of URLs
        """
        path = Path(filepath)

        if not path.exists():
            logger.error(f"URL file not found: {filepath}")
            return []

        with path.open() as f:
            urls = [
                line.strip()
                for line in f
                if line.strip() and not line.startswith("#")
            ]

        logger.info(f"Loaded {len(urls)} URLs from {filepath}")
        return urls

    def process_url(self, url: str) -> bool:
        """
        Process a single URL.

        Args:
            url: Competition URL

        Returns:
            True if successful
        """
        try:
            # Check if already in checkpoint
            if url in self.processed_urls:
                logger.info(f"⏭️  Already processed (checkpoint): {url}")
                self.stats["skipped"] += 1
                return True

            # Check if already in database
            if self.grant_store.exists_by_url(url):
                logger.info(f"⏭️  Already in database: {url}")
                self._save_checkpoint(url)
                self.processed_urls.add(url)
                self.stats["skipped"] += 1
                return True

            # Step 1: Scrape
            logger.info(f"📥 Scraping: {url}")
            scraped = self.scraper.scrape_competition(url)

            # Step 2: Ingest resources
            logger.info(f"📄 Ingesting resources...")
            resource_docs = self.ingestor.fetch_documents_for_resources(
                scraped.resources,
                existing_hashes=self.existing_hashes,
            )

            # Step 3: Normalize
            logger.info(f"🔄 Normalizing...")
            grant, indexable_docs = normalize_scraped_competition(
                scraped,
                resource_docs,
            )

            # Step 4: Persist
            logger.info(f"💾 Saving to database...")
            self.grant_store.upsert_grant(grant)
            self.doc_store.upsert_documents(indexable_docs)

            # Step 5: Index
            logger.info(f"🔍 Indexing...")
            self.vector_index.index_documents(indexable_docs)

            # Update stats
            self.stats["processed"] += 1
            self.stats["total_documents"] += len(indexable_docs)

            # Save checkpoint
            self._save_checkpoint(url)
            self.processed_urls.add(url)

            logger.info(
                f"✅ Success: {grant.title} "
                f"({len(indexable_docs)} docs, {len(scraped.resources)} resources)"
            )

            return True

        except Exception as e:
            logger.error(f"❌ Failed: {url}")
            logger.exception(e)
            self.stats["failed"] += 1
            return False

    def run(self, urls: list):
        """
        Run batch ingestion.

        Args:
            urls: List of URLs to process
        """
        self.stats["total"] = len(urls)

        logger.info("=" * 80)
        logger.info("BATCH INGESTION - STARTING")
        logger.info("=" * 80)
        logger.info(f"Total URLs: {len(urls)}")
        logger.info(f"Batch size: {self.batch_size}")
        logger.info(f"Delay range: {self.min_delay}-{self.max_delay}s")
        logger.info(f"Database: {self.db_path}")
        logger.info(f"Checkpoint: {self.checkpoint_file}")
        logger.info("=" * 80)

        # Shuffle to avoid patterns
        random.shuffle(urls)

        # Process in batches
        num_batches = (len(urls) + self.batch_size - 1) // self.batch_size

        for batch_num in range(num_batches):
            start_idx = batch_num * self.batch_size
            end_idx = min(start_idx + self.batch_size, len(urls))
            batch = urls[start_idx:end_idx]

            logger.info(f"\n{'=' * 80}")
            logger.info(f"BATCH {batch_num + 1}/{num_batches}")
            logger.info(f"{'=' * 80}")

            for i, url in enumerate(batch, 1):
                logger.info(f"\n[{start_idx + i}/{len(urls)}] Processing...")

                success = self.process_url(url)

                # Rate limiting
                if i < len(batch):  # Don't delay after last URL in batch
                    delay = random.uniform(self.min_delay, self.max_delay)
                    logger.info(f"⏸️  Waiting {delay:.1f}s...")
                    time.sleep(delay)

            # Batch complete
            logger.info(f"\n✓ Batch {batch_num + 1} complete")
            self._print_stats()

        # Final summary
        logger.info(f"\n{'=' * 80}")
        logger.info("BATCH INGESTION - COMPLETE")
        logger.info(f"{'=' * 80}")
        self._print_stats()
        logger.info(f"{'=' * 80}")

    def _print_stats(self):
        """Print current statistics."""
        logger.info(f"Progress: {self.stats['processed'] + self.stats['skipped']}/{self.stats['total']}")
        logger.info(f"  Processed: {self.stats['processed']}")
        logger.info(f"  Skipped:   {self.stats['skipped']}")
        logger.info(f"  Failed:    {self.stats['failed']}")
        logger.info(f"  Documents: {self.stats['total_documents']}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Batch ingest Innovate UK competitions"
    )
    parser.add_argument(
        "--input",
        default="innovate_uk_links.txt",
        help="Input file with URLs"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="URLs per batch"
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=1.0,
        help="Minimum delay between requests (seconds)"
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=2.0,
        help="Maximum delay between requests (seconds)"
    )
    parser.add_argument(
        "--checkpoint",
        default="processed_urls.txt",
        help="Checkpoint file for resume capability"
    )

    args = parser.parse_args()

    # Create ingestor
    ingestor = BatchIngestor(
        batch_size=args.batch_size,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        checkpoint_file=args.checkpoint,
    )

    # Load URLs
    urls = ingestor.load_urls(args.input)

    if not urls:
        logger.error("No URLs to process")
        return

    # Run
    ingestor.run(urls)

    # Post-ingestion: Auto-fix funding amounts
    logger.info(f"\n{'=' * 80}")
    logger.info("POST-INGESTION: FUNDING NORMALIZATION")
    logger.info(f"{'=' * 80}")

    try:
        # Import and run funding normalization
        sys.path.insert(0, str(project_root / "scripts"))
        from migrate_fix_upstream_funding import run_funding_normalization

        stats = run_funding_normalization(db_path=ingestor.db_path)

        logger.info(f"✅ Funding normalization complete:")
        logger.info(f"   Manual corrections:    {stats['manual_corrections']}")
        logger.info(f"   Automatic corrections: {stats['automatic_corrections']}")
        logger.info(f"   Total corrections:     {stats['total_corrections']}")

    except Exception as e:
        logger.warning(f"⚠️  Funding normalization failed: {e}")
        logger.warning("   (This is non-critical - ingestion was successful)")

    # Post-ingestion: Decimal refinement from documents
    logger.info(f"\n{'=' * 80}")
    logger.info("POST-INGESTION: DECIMAL FUNDING REFINEMENT")
    logger.info(f"{'=' * 80}")

    try:
        from migrate_refine_funding_decimals import run_decimal_refinement

        stats = run_decimal_refinement(db_path=ingestor.db_path)

        logger.info(f"✅ Decimal refinement complete:")
        logger.info(f"   Updated:  {stats['updated']} grant(s)")
        logger.info(f"   Skipped:  {stats['skipped']} grant(s)")
        logger.info(f"   Total:    {stats['total']} grant(s) processed")

    except Exception as e:
        logger.warning(f"⚠️  Decimal refinement failed: {e}")
        logger.warning("   (This is non-critical - ingestion was successful)")

    # Post-ingestion: Prize funding detection
    logger.info(f"\n{'=' * 80}")
    logger.info("POST-INGESTION: PRIZE FUNDING DETECTION")
    logger.info(f"{'=' * 80}")

    try:
        from migrate_fix_prize_funding import run_prize_funding_patch

        stats = run_prize_funding_patch(db_path=ingestor.db_path)

        logger.info(f"✅ Prize funding detection complete:")
        logger.info(f"   Patches applied: {stats['prize_patches_applied']}/{stats['total_prize_patches']}")

    except Exception as e:
        logger.warning(f"⚠️  Prize funding detection failed: {e}")
        logger.warning("   (This is non-critical - ingestion was successful)")

    logger.info(f"{'=' * 80}")


if __name__ == "__main__":
    main()
