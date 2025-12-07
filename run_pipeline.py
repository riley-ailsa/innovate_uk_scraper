#!/usr/bin/env python3
"""
Innovate UK Grant Scraper - Pipeline v3 (Sectioned Schema)

Usage:
    python run_pipeline.py                    # Full pipeline
    python run_pipeline.py --limit 5          # Test with 5 grants
    python run_pipeline.py --dry-run          # Scrape but don't save
"""

import os
import re
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from tqdm import tqdm

from ailsa_shared import (
    Grant, GrantSource, GrantStatus, GrantSections,
    SummarySection, EligibilitySection, ScopeSection,
    DatesSection, FundingSection, HowToApplySection,
    AssessmentSection, SupportingInfoSection, ContactsSection,
    SupportingDocument, ProgrammeInfo, ProcessingInfo, CompetitionType,
    MongoDBClient, PineconeClientV3,
    clean_html, parse_date, parse_money, infer_status_from_dates,
)

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

IUK_SEARCH_URL = "https://apply-for-innovation-funding.service.gov.uk/competition/search"
IUK_BASE_URL = "https://apply-for-innovation-funding.service.gov.uk"

DATA_DIR = Path(__file__).parent / "data"
LOG_DIR = Path(__file__).parent / "logs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


# =============================================================================
# DISCOVERY
# =============================================================================

def discover_grant_urls() -> List[str]:
    """Discover all Innovate UK competition URLs."""
    logger.info("Discovering Innovate UK competitions...")
    
    urls = set()
    page = 1
    
    while True:
        page_url = f"{IUK_SEARCH_URL}?page={page}"
        
        try:
            response = requests.get(page_url, headers=HEADERS, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error fetching page {page}: {e}")
            break
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find competition links
        links = soup.select('a[href*="/competition/"]')
        page_urls = set()
        
        for link in links:
            href = link.get('href', '')
            if '/competition/' in href and '/search' not in href:
                # Extract competition ID
                match = re.search(r'/competition/(\d+)', href)
                if match:
                    comp_id = match.group(1)
                    full_url = f"{IUK_BASE_URL}/competition/{comp_id}/overview"
                    page_urls.add(full_url)
        
        if not page_urls:
            break
        
        new_urls = page_urls - urls
        if not new_urls:
            break
        
        urls.update(page_urls)
        logger.info(f"Page {page}: found {len(new_urls)} new competitions")
        page += 1
        
        if page > 50:
            break
    
    logger.info(f"Discovered {len(urls)} total competitions")
    return list(urls)


# =============================================================================
# SCRAPING
# =============================================================================

def scrape_grant_page(url: str) -> Optional[Dict[str, Any]]:
    """Scrape a single Innovate UK competition page."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Error fetching {url}: {e}")
        return None
    
    soup = BeautifulSoup(response.text, 'lxml')
    
    raw = {
        'url': url,
        'scraped_at': datetime.now(timezone.utc),
    }
    
    # Extract competition ID from URL
    match = re.search(r'/competition/(\d+)', url)
    if match:
        raw['competition_id'] = match.group(1)
    
    # Title
    title_elem = soup.select_one('h1')
    if title_elem:
        title = title_elem.get_text(strip=True)
        # Remove "Funding competition" prefix
        title = re.sub(r'^Funding competition\s*', '', title)
        raw['title'] = title
    
    # Competition dates and status from header info
    for dt in soup.select('dt'):
        label = dt.get_text(strip=True).lower()
        dd = dt.find_next_sibling('dd')
        if dd:
            value = dd.get_text(strip=True)
            
            if 'opens' in label:
                raw['opening_date'] = value
            elif 'closes' in label:
                raw['closing_date'] = value
            elif 'status' in label:
                raw['status'] = value
    
    # Tab content - scrape each tab
    tabs = ['summary', 'eligibility', 'scope', 'dates', 'how-to-apply', 'supporting-information']
    
    for tab in tabs:
        tab_url = url.replace('/overview', f'/{tab}')
        try:
            tab_response = requests.get(tab_url, headers=HEADERS, timeout=30)
            if tab_response.status_code == 200:
                tab_soup = BeautifulSoup(tab_response.text, 'lxml')
                content = tab_soup.select_one('.govuk-main-wrapper, main, article')
                if content:
                    raw[f'{tab.replace("-", "_")}_text'] = content.get_text(separator='\n', strip=True)
                    raw[f'{tab.replace("-", "_")}_html'] = str(content)
        except:
            pass
    
    return raw


# =============================================================================
# NORMALIZATION
# =============================================================================

def normalize_grant(raw: Dict[str, Any]) -> Grant:
    """Convert raw Innovate UK data to Grant schema v3."""
    
    opens_at = parse_date(raw.get('opening_date'))
    closes_at = parse_date(raw.get('closing_date'))
    status = infer_status_from_dates(opens_at, closes_at, raw.get('status'))
    
    external_id = raw.get('competition_id', '')
    grant_id = f"innovate_uk_{external_id}"
    
    # Detect competition type
    comp_type = detect_competition_type(raw)
    
    sections = GrantSections(
        summary=SummarySection(
            text=clean_html(raw.get('summary_text', '')),
            html=raw.get('summary_html'),
            extracted_at=datetime.now(timezone.utc),
        ),
        
        eligibility=EligibilitySection(
            text=clean_html(raw.get('eligibility_text', '')),
            who_can_apply=extract_who_can_apply(raw),
            geographic_scope="UK",
            uk_registered_required=True,
            extracted_at=datetime.now(timezone.utc),
        ),
        
        scope=ScopeSection(
            text=clean_html(raw.get('scope_text', '')),
            themes=extract_themes(raw),
            sectors=extract_sectors(raw),
            trl_range=extract_trl(raw),
            extracted_at=datetime.now(timezone.utc),
        ),
        
        dates=DatesSection(
            opens_at=opens_at,
            closes_at=closes_at,
            deadline_time=extract_deadline_time(raw.get('closing_date', '')),
            key_dates_text=clean_html(raw.get('dates_text', '')),
            extracted_at=datetime.now(timezone.utc),
        ),
        
        funding=FundingSection(
            text=extract_funding_text(raw),
            total_pot_gbp=parse_money(extract_total_funding(raw)),
            total_pot_display=extract_total_funding(raw),
            per_project_max_gbp=parse_money(extract_project_funding(raw)),
            competition_type=comp_type,
            currency="GBP",
            extracted_at=datetime.now(timezone.utc),
        ),
        
        how_to_apply=HowToApplySection(
            text=clean_html(raw.get('how_to_apply_text', '')),
            portal_name="Innovation Funding Service",
            portal_url=raw.get('url'),
            extracted_at=datetime.now(timezone.utc),
        ),
        
        assessment=AssessmentSection(
            text=extract_assessment_text(raw),
            criteria=extract_assessment_criteria(raw),
            extracted_at=datetime.now(timezone.utc),
        ),
        
        supporting_info=SupportingInfoSection(
            text=clean_html(raw.get('supporting_information_text', '')),
            extracted_at=datetime.now(timezone.utc),
        ),
        
        contacts=ContactsSection(
            helpdesk_email="support@iuk.ukri.org",
            extracted_at=datetime.now(timezone.utc),
        ),
    )
    
    return Grant(
        grant_id=grant_id,
        source=GrantSource.INNOVATE_UK,
        external_id=external_id,
        title=raw.get('title', ''),
        url=raw.get('url', ''),
        status=status,
        is_active=(status == GrantStatus.OPEN),
        sections=sections,
        programme=ProgrammeInfo(
            funder="UKRI / Innovate UK",
            competition_code=external_id,
        ),
        tags=generate_tags(raw, comp_type),
        raw=raw,
        processing=ProcessingInfo(
            scraped_at=raw.get('scraped_at'),
            normalized_at=datetime.now(timezone.utc),
            schema_version="3.0",
        ),
    )


# =============================================================================
# HELPERS
# =============================================================================

def detect_competition_type(raw: Dict) -> CompetitionType:
    """Detect if grant, loan, or prize."""
    text = (raw.get('title', '') + raw.get('summary_text', '')).lower()
    
    if 'loan' in text:
        return CompetitionType.LOAN
    elif 'prize' in text:
        return CompetitionType.PRIZE
    elif 'contract' in text:
        return CompetitionType.CONTRACT
    return CompetitionType.GRANT


def extract_who_can_apply(raw: Dict) -> List[str]:
    """Extract eligible applicant types."""
    who_can = []
    text = raw.get('eligibility_text', '').lower()
    
    if 'sme' in text or 'small' in text or 'micro' in text:
        who_can.append('SME')
    if 'large' in text or 'enterprise' in text:
        who_can.append('Large Enterprise')
    if 'academic' in text or 'universit' in text or 'research org' in text:
        who_can.append('Academic')
    if 'rto' in text or 'catapult' in text:
        who_can.append('RTO')
    if 'charity' in text or 'not-for-profit' in text:
        who_can.append('Charity')
    
    return who_can if who_can else ['Business']


def extract_themes(raw: Dict) -> List[str]:
    """Extract themes from scope."""
    themes = []
    text = (raw.get('scope_text', '') + raw.get('summary_text', '')).lower()
    
    theme_map = {
        'artificial intelligence': 'AI',
        'machine learning': 'AI',
        'net zero': 'Net Zero',
        'clean tech': 'Clean Tech',
        'health': 'Health',
        'life sciences': 'Life Sciences',
        'manufacturing': 'Manufacturing',
        'aerospace': 'Aerospace',
        'automotive': 'Automotive',
        'agri': 'AgriTech',
        'food': 'Food',
        'space': 'Space',
        'quantum': 'Quantum',
        'cyber': 'Cyber Security',
    }
    
    for keyword, theme in theme_map.items():
        if keyword in text and theme not in themes:
            themes.append(theme)
    
    return themes


def extract_sectors(raw: Dict) -> List[str]:
    """Extract sectors."""
    sectors = []
    text = raw.get('scope_text', '').lower()
    
    sector_map = {
        'health': 'Healthcare',
        'manufact': 'Manufacturing',
        'energy': 'Energy',
        'transport': 'Transport',
        'defence': 'Defence',
        'finance': 'Financial Services',
        'creative': 'Creative Industries',
        'construction': 'Construction',
    }
    
    for keyword, sector in sector_map.items():
        if keyword in text and sector not in sectors:
            sectors.append(sector)
    
    return sectors


def extract_trl(raw: Dict) -> Optional[str]:
    """Extract TRL range."""
    text = raw.get('scope_text', '') + raw.get('eligibility_text', '')
    match = re.search(r'TRL\s*(\d+)\s*[-–to]+\s*(\d+)', text, re.IGNORECASE)
    if match:
        return f"TRL {match.group(1)}-{match.group(2)}"
    return None


def extract_deadline_time(closing_date: str) -> Optional[str]:
    """Extract deadline time."""
    if not closing_date:
        return None
    match = re.search(r'(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)', closing_date, re.IGNORECASE)
    return match.group(1) if match else None


def extract_funding_text(raw: Dict) -> str:
    """Extract funding text from summary."""
    text = raw.get('summary_text', '')
    match = re.search(r'(£[\d,.]+ (?:million|billion|m|bn).*?)(?:\.|$)', text, re.IGNORECASE)
    return match.group(0) if match else ''


def extract_total_funding(raw: Dict) -> Optional[str]:
    """Extract total funding pot."""
    text = raw.get('summary_text', '') + raw.get('scope_text', '')
    # Look for "share of £X million"
    match = re.search(r'share of (£[\d,.]+ (?:million|m|billion|bn))', text, re.IGNORECASE)
    return match.group(1) if match else None


def extract_project_funding(raw: Dict) -> Optional[str]:
    """Extract per-project funding."""
    text = raw.get('summary_text', '') + raw.get('scope_text', '')
    # Look for project funding ranges
    match = re.search(r'projects? (?:of |up to )?(£[\d,.]+ ?(?:k|thousand|million|m)?)', text, re.IGNORECASE)
    return match.group(1) if match else None


def extract_assessment_text(raw: Dict) -> str:
    """Extract assessment info from how-to-apply."""
    text = raw.get('how_to_apply_text', '')
    # Look for assessment section
    match = re.search(r'(?:assessment|scoring|criteria)(.{500,}?)(?:how to apply|submit|$)', 
                      text, re.IGNORECASE | re.DOTALL)
    return clean_html(match.group(0)) if match else ''


def extract_assessment_criteria(raw: Dict) -> List[str]:
    """Extract assessment criteria."""
    criteria = []
    text = raw.get('how_to_apply_text', '')
    
    standard_criteria = ['Innovation', 'Impact', 'Team', 'Value for money', 'Deliverability']
    for criterion in standard_criteria:
        if criterion.lower() in text.lower():
            criteria.append(criterion)
    
    return criteria


def generate_tags(raw: Dict, comp_type: CompetitionType) -> List[str]:
    """Generate tags."""
    tags = ['innovate_uk', 'ukri', 'uk']
    
    if comp_type:
        tags.append(comp_type.value)
    
    # Add themes as tags
    themes = extract_themes(raw)
    tags.extend([t.lower().replace(' ', '_') for t in themes])
    
    return tags


# =============================================================================
# INGESTION
# =============================================================================

def ingest_grants(grants: List[Grant], dry_run: bool = False):
    """Save to MongoDB and Pinecone."""
    if dry_run:
        logger.info(f"DRY RUN: Would ingest {len(grants)} grants")
        return
    
    logger.info("Saving to MongoDB...")
    mongo = MongoDBClient()
    success, errors = mongo.upsert_grants(grants)
    logger.info(f"MongoDB: {success} saved, {errors} errors")
    
    logger.info("Creating embeddings...")
    pinecone = PineconeClientV3()
    for grant in tqdm(grants, desc="Embedding"):
        try:
            pinecone.embed_and_upsert_grant(grant)
        except Exception as e:
            logger.error(f"Error embedding {grant.grant_id}: {e}")


# =============================================================================
# MAIN
# =============================================================================

def run_pipeline(limit: Optional[int] = None, dry_run: bool = False):
    """Run the full pipeline."""
    logger.info("=" * 60)
    logger.info("Innovate UK Scraper Pipeline v3")
    logger.info("=" * 60)
    
    urls = discover_grant_urls()
    if limit:
        urls = urls[:limit]
    
    logger.info(f"Scraping {len(urls)} competitions...")
    raw_grants = []
    for url in tqdm(urls, desc="Scraping"):
        raw = scrape_grant_page(url)
        if raw:
            raw_grants.append(raw)
    
    logger.info(f"Normalizing {len(raw_grants)} grants...")
    grants = []
    for raw in raw_grants:
        try:
            grant = normalize_grant(raw)
            grants.append(grant)
        except Exception as e:
            logger.error(f"Error normalizing: {e}")
    
    ingest_grants(grants, dry_run=dry_run)
    
    logger.info(f"Complete: {len(grants)} grants processed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    
    run_pipeline(limit=args.limit, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
