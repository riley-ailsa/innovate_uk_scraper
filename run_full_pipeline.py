#!/usr/bin/env python3
"""
Ingest Innovate UK grants into production MongoDB + Pinecone.

Features:
- Retry logic with exponential backoff
- Rate limiting between requests
- Monitoring and failure tracking
- Enhanced error logging
- Dead letter queue for persistent failures
"""

import os
import sys
import time
import logging
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

import openai
import requests
from pymongo import MongoClient
from pinecone import Pinecone
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'logs/scraper_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
    ]
)
logger = logging.getLogger(__name__)

# Ensure logs directory exists
Path("logs").mkdir(exist_ok=True)

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ailsa-grants")
MONGO_URI = os.getenv("MONGODB_URI", os.getenv("MONGO_URI", "mongodb://localhost:27017"))

openai.api_key = OPENAI_API_KEY

# Initialize clients
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX_NAME)

# MongoDB connection
mongo_client = MongoClient(MONGO_URI)
db = mongo_client.ailsa_grants
grants_collection = db.grants


# Import scraper components
from src.ingest.innovateuk_competition import InnovateUKCompetitionScraper
from src.ingest.resource_ingestor import ResourceIngestor
from src.normalize.innovate_uk import normalize_scraped_competition
from src.monitoring.scraper_stats import ScraperMonitor
from src.core.constants import (
    EMBEDDING_MODEL,
    MAX_DESCRIPTION_LENGTH,
    DESCRIPTION_TRUNCATE_START,
    DESCRIPTION_TRUNCATE_END,
    MAX_SECTION_LENGTH,
    MIN_SECTION_LENGTH,
)


def load_urls(filepath: str) -> List[str]:
    """Load competition URLs from file"""
    path = Path(filepath)

    if not path.exists():
        print(f"❌ File not found: {filepath}")
        return []

    with path.open() as f:
        urls = [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]

    print(f"📁 Loaded {len(urls)} URLs from {filepath}")
    return urls


def extract_embedding_text(grant: Dict[str, Any], sections: List[Dict[str, Any]]) -> str:
    """
    Extract rich text for embedding from grant + sections.

    Combines title, description, and key section content.
    Uses constants for text length limits.
    """
    parts = []

    # Title
    if grant.get('title'):
        parts.append(f"Title: {grant['title']}")

    # Programme
    parts.append(f"Programme: Innovate UK")

    # Status and dates
    if grant.get('is_active'):
        parts.append(f"Status: Active")
    else:
        parts.append(f"Status: Closed")

    if grant.get('closes_at'):
        parts.append(f"Deadline: {grant['closes_at']}")

    # Funding
    if grant.get('total_fund'):
        parts.append(f"Funding: {grant['total_fund']}")

    # Competition type
    if grant.get('competition_type'):
        parts.append(f"Type: {grant['competition_type'].title()}")

    # Per-project funding
    if grant.get('project_funding_max'):
        funding_str = f"Per-project: up to £{grant['project_funding_max']:,}"
        if grant.get('project_funding_min'):
            funding_str = f"Per-project: £{grant['project_funding_min']:,} to £{grant['project_funding_max']:,}"
        parts.append(funding_str)

    # Expected winners
    if grant.get('expected_winners'):
        parts.append(f"Expected winners: ~{grant['expected_winners']}")

    # Description
    if grant.get('description'):
        desc = grant['description']
        if len(desc) > MAX_DESCRIPTION_LENGTH:
            desc = desc[:DESCRIPTION_TRUNCATE_START] + "\n...\n" + desc[-DESCRIPTION_TRUNCATE_END:]
        parts.append(f"\nDescription:\n{desc}")

    # Add key sections (summary, eligibility, scope)
    for section in sections:
        if section.get('section_name') in ['summary', 'eligibility', 'scope']:
            text = section.get('text', '')
            if text and len(text) > MIN_SECTION_LENGTH:
                # Limit section length
                section_text = text[:MAX_SECTION_LENGTH] if len(text) > MAX_SECTION_LENGTH else text
                parts.append(f"\n{section['section_name'].title()}:\n{section_text}")

    return "\n".join(parts)


def ingest_competition(
    url: str,
    scraper: InnovateUKCompetitionScraper,
    ingestor: ResourceIngestor,
    monitor: Optional[ScraperMonitor] = None,
) -> Dict[str, Any]:
    """
    Ingest one Innovate UK competition into MongoDB + Pinecone.

    Features:
    - Detects and logs changes from previous scrape
    - Enhanced error logging with error type classification
    - Monitoring integration for failure tracking

    Args:
        url: Competition URL to scrape
        scraper: Configured scraper instance
        ingestor: Resource ingestor instance
        monitor: Optional ScraperMonitor for tracking

    Returns:
        dict: {'success': bool, 'is_new': bool, 'changed': bool, 'changes': list, 'error_type': str}
    """
    start_time = time.time()
    comp_id = url.split('/')[-3] if '/' in url else 'unknown'

    try:
        # Step 1: Scrape
        logger.info(f"Scraping competition {comp_id}: {url}")
        print(f"  📥 Scraping...")
        scraped = scraper.scrape_competition(url)

        # Step 2: Ingest resources (skip for now - can be slow)
        resource_docs = []

        # Step 3: Normalize
        grant, indexable_docs = normalize_scraped_competition(scraped, resource_docs)

        logger.info(f"Normalized: {grant.title[:60]}... (type={grant.competition_type})")
        print(f"  ✅ {grant.title[:60]}...")

        # Step 4: Check for existing grant to detect changes
        old_grant = grants_collection.find_one({"grant_id": grant.id})
        changes = []
        is_new = old_grant is None

        # Prepare MongoDB document
        status = "active" if grant.is_active else "closed"

        grant_doc = {
            "grant_id": grant.id,
            "source": grant.source,
            "title": grant.title,
            "url": grant.url,
            "external_id": grant.external_id,

            # Status
            "status": status,
            "is_active": grant.is_active,
            "opens_at": grant.opens_at,
            "closes_at": grant.closes_at,

            # Funding
            "total_fund_gbp": grant.total_fund_gbp,
            "total_fund_display": grant.total_fund,
            "project_funding_min": grant.project_funding_min,
            "project_funding_max": grant.project_funding_max,
            "expected_winners": grant.expected_winners,
            "competition_type": grant.competition_type,

            # Description
            "description": grant.description,
            "description_summary": grant.description[:500] if grant.description else None,

            # Classification
            "tags": grant.tags,

            # Sections (embedded array)
            "sections": [
                {
                    "name": doc.section_name,
                    "text": doc.text,
                    "url": doc.source_url
                }
                for doc in indexable_docs if doc.section_name
            ],

            # Resources (embedded array)
            "resources": [
                {
                    "id": doc.resource_id,
                    "type": doc.doc_type,
                    "url": doc.source_url,
                    "citation": doc.citation_text
                }
                for doc in indexable_docs if doc.resource_id
            ],

            # Timestamps
            "scraped_at": grant.scraped_at,
            "updated_at": datetime.utcnow(),
        }

        # Detect changes from old document
        if old_grant:
            if old_grant.get("status") != grant_doc["status"]:
                changes.append(f"Status: {old_grant.get('status')} → {grant_doc['status']}")
            if old_grant.get("closes_at") != grant_doc["closes_at"]:
                old_close = old_grant.get("closes_at")
                new_close = grant_doc["closes_at"]
                changes.append(f"Deadline: {old_close} → {new_close}")
            if old_grant.get("total_fund_gbp") != grant_doc["total_fund_gbp"]:
                old_budget = old_grant.get("total_fund_gbp")
                new_budget = grant_doc["total_fund_gbp"]
                old_budget_str = f"£{old_budget:,}" if old_budget else "N/A"
                new_budget_str = f"£{new_budget:,}" if new_budget else "N/A"
                changes.append(f"Budget: {old_budget_str} → {new_budget_str}")
            if old_grant.get("title") != grant_doc["title"]:
                changes.append(f"Title changed")

        # Step 5: Upsert to MongoDB
        result = grants_collection.update_one(
            {"grant_id": grant.id},
            {
                "$set": grant_doc,
                "$setOnInsert": {"created_at": datetime.utcnow()}
            },
            upsert=True
        )

        # Check if it was an insert
        is_new = result.upserted_id is not None

        if is_new:
            logger.info(f"NEW competition: {grant.id}")
            print(f"  🆕 NEW competition")
        elif changes:
            logger.info(f"UPDATED competition {grant.id}: {', '.join(changes)}")
            print(f"  🔄 CHANGES: {', '.join(changes)}")
        else:
            print(f"  ✓ No changes")

        print(f"  ✅ Saved to MongoDB")

        # Step 6: Generate embedding
        print(f"  🔮 Generating embedding...")
        embedding_text = extract_embedding_text(
            {
                'title': grant.title,
                'description': grant.description,
                'total_fund': grant.total_fund,
                'is_active': grant.is_active,
                'closes_at': grant.closes_at,
                'competition_type': grant.competition_type,
                'project_funding_min': grant.project_funding_min,
                'project_funding_max': grant.project_funding_max,
                'expected_winners': grant.expected_winners,
            },
            [
                {
                    'section_name': doc.section_name,
                    'text': doc.text
                }
                for doc in indexable_docs
                if doc.section_name
            ]
        )

        response = openai.embeddings.create(
            input=embedding_text,
            model=EMBEDDING_MODEL
        )
        embedding = response.data[0].embedding

        # Step 7: Upsert to Pinecone with metadata
        print(f"  📌 Upserting to Pinecone...")
        close_date_str = grant.closes_at.isoformat() if grant.closes_at else ''
        index.upsert(vectors=[{
            'id': grant.id,
            'values': embedding,
            'metadata': {
                'source': 'innovate_uk',
                'title': grant.title[:500] if grant.title else '',
                'status': status,
                'close_date': close_date_str,
                'url': grant.url,
                'tags': ','.join(grant.tags[:5]) if grant.tags else '',
                'budget_min': str(grant.total_fund_gbp) if grant.total_fund_gbp else '',
                'budget_max': str(grant.total_fund_gbp) if grant.total_fund_gbp else '',
                'total_fund': grant.total_fund or '',
                'competition_type': grant.competition_type,
                'project_funding_min': str(grant.project_funding_min) if grant.project_funding_min else '',
                'project_funding_max': str(grant.project_funding_max) if grant.project_funding_max else '',
                'expected_winners': str(grant.expected_winners) if grant.expected_winners else '',
            }
        }])

        print(f"  ✅ Indexed in Pinecone")

        duration_ms = int((time.time() - start_time) * 1000)

        # Log to monitor
        if monitor:
            monitor.log_attempt(
                competition_id=comp_id,
                url=url,
                success=True,
                duration_ms=duration_ms,
                is_new=is_new,
                has_changes=len(changes) > 0,
            )

        return {
            'success': True,
            'is_new': is_new,
            'changed': len(changes) > 0,
            'changes': changes,
            'error_type': None,
        }

    except requests.exceptions.SSLError as e:
        error_msg = f"SSL certificate error: {str(e)[:200]}"
        logger.error(f"SSL error scraping {url}: {e}")
        logger.debug(traceback.format_exc())
        print(f"  ❌ SSL Error: {str(e)[:100]}")

        if monitor:
            monitor.log_attempt(
                competition_id=comp_id,
                url=url,
                success=False,
                error=error_msg,
                error_type="ssl",
                duration_ms=int((time.time() - start_time) * 1000),
            )

        return {
            'success': False,
            'is_new': False,
            'changed': False,
            'changes': [],
            'error_type': 'ssl',
        }

    except requests.RequestException as e:
        error_msg = f"Network error: {str(e)[:200]}"
        logger.error(f"Network error scraping {url}: {e}")
        logger.debug(traceback.format_exc())
        print(f"  ❌ Network Error: {str(e)[:100]}")

        if monitor:
            monitor.log_attempt(
                competition_id=comp_id,
                url=url,
                success=False,
                error=error_msg,
                error_type="network",
                duration_ms=int((time.time() - start_time) * 1000),
            )

        return {
            'success': False,
            'is_new': False,
            'changed': False,
            'changes': [],
            'error_type': 'network',
        }

    except Exception as e:
        error_msg = f"Unexpected error: {type(e).__name__}: {str(e)[:200]}"
        logger.error(f"Unexpected error scraping {url}: {e}")
        logger.debug(traceback.format_exc())
        print(f"  ❌ Error: {type(e).__name__}: {str(e)[:100]}")

        if monitor:
            monitor.log_attempt(
                competition_id=comp_id,
                url=url,
                success=False,
                error=error_msg,
                error_type="unknown",
                duration_ms=int((time.time() - start_time) * 1000),
            )

        return {
            'success': False,
            'is_new': False,
            'changed': False,
            'changes': [],
            'error_type': 'unknown',
        }


def main():
    """Main ingestion pipeline with monitoring and failure tracking."""
    print("=" * 70)
    print("INGESTING INNOVATE UK GRANTS TO PRODUCTION")
    print("=" * 70)

    logger.info("Starting Innovate UK ingestion pipeline")

    # Load URLs
    urls = load_urls("innovate_uk_urls.txt")
    if not urls:
        print("❌ No URLs to process")
        logger.error("No URLs found to process")
        return

    # Initialize scraper, ingestor, and monitor
    scraper = InnovateUKCompetitionScraper()
    ingestor = ResourceIngestor()
    monitor = ScraperMonitor()

    # Process each URL
    success_count = 0
    fail_count = 0
    new_count = 0
    changed_count = 0
    unchanged_count = 0
    all_changes = []

    print(f"\n🚀 Processing {len(urls)} competitions...\n")
    logger.info(f"Processing {len(urls)} competitions")

    for i, url in enumerate(tqdm(urls, desc="Ingesting"), 1):
        comp_id = url.split('/')[-3]
        print(f"\n[{i}/{len(urls)}] Competition {comp_id}")

        result = ingest_competition(url, scraper, ingestor, monitor)

        if result['success']:
            success_count += 1
            if result['is_new']:
                new_count += 1
            elif result['changed']:
                changed_count += 1
                all_changes.append({
                    'competition_id': comp_id,
                    'changes': result['changes']
                })
            else:
                unchanged_count += 1
        else:
            fail_count += 1

    # Finalize monitoring
    stats = monitor.finalize()

    # Export failures if any
    if stats.failed > 0:
        failures_path = f"logs/failed_competitions_{monitor.run_id}.json"
        monitor.export_failures(failures_path)
        logger.warning(f"Exported {stats.failed} failures to {failures_path}")

    # Export stats
    stats_path = f"logs/scraper_stats_{monitor.run_id}.json"
    monitor.export_stats(stats_path)

    # Final stats from MongoDB
    mongo_count = grants_collection.count_documents({"source": "innovate_uk"})

    pinecone_stats = index.describe_index_stats()

    print(f"\n" + "=" * 70)
    print("INGESTION COMPLETE")
    print("=" * 70)
    print(f"✅ Success: {success_count}")
    print(f"❌ Failed: {fail_count}")
    print(f"📊 Success Rate: {stats.success_rate:.1f}%")
    print(f"")
    print(f"📊 Changes Detected:")
    print(f"   🆕 New: {new_count}")
    print(f"   🔄 Updated: {changed_count}")
    print(f"   ✓ Unchanged: {unchanged_count}")
    print(f"")
    print(f"📊 MongoDB (Innovate UK): {mongo_count} grants")
    print(f"📊 Pinecone (Total): {pinecone_stats['total_vector_count']} vectors")

    # Show error summary if there were failures
    error_summary = monitor.get_error_summary()
    if error_summary:
        print(f"\n⚠️ ERROR SUMMARY:")
        for error_type, count in error_summary.items():
            print(f"   {error_type}: {count}")

    # Show persistent failures
    persistent_failures = monitor.get_failed_competitions()
    if persistent_failures:
        print(f"\n🚨 PERSISTENT FAILURES ({len(persistent_failures)} competitions):")
        for comp_id, count in list(persistent_failures.items())[:5]:
            print(f"   Competition {comp_id}: {count} failures")
        if len(persistent_failures) > 5:
            print(f"   ... and {len(persistent_failures) - 5} more")

    if all_changes:
        print(f"\n🔄 DETAILED CHANGES:")
        for item in all_changes:
            print(f"\n   Competition {item['competition_id']}:")
            for change in item['changes']:
                print(f"      • {change}")

    # Check if alerting is needed
    if monitor.should_alert():
        alert_msg = monitor.get_alert_message()
        print(f"\n🚨 ALERT:")
        print(alert_msg)
        logger.warning(f"Scraper alert triggered: {alert_msg}")

    print("=" * 70)

    logger.info(
        f"Ingestion complete: {success_count} success, {fail_count} failed, "
        f"{new_count} new, {changed_count} updated"
    )

    mongo_client.close()


if __name__ == "__main__":
    main()
