"""
Normalization functions for Innovate UK scraper output.

Converts ScrapedCompetition objects into canonical domain models:
- Grant (canonical competition)
- IndexableDocument (sections + resources)

Includes:
- Competition type detection (grant/loan/prize)
- Per-project funding extraction
- Expected winners calculation
"""

import re
from datetime import datetime
from typing import List, Tuple, Optional

from src.core.domain_models import Grant, IndexableDocument
from src.ingest.innovatuk_types import ScrapedCompetition
from src.core.models import Document
from src.core.money import parse_gbp_amount
from src.core.time_utils import infer_status
from src.core.constants import (
    COMPETITION_TYPE_GRANT,
    COMPETITION_TYPE_LOAN,
    COMPETITION_TYPE_PRIZE,
    TYPICAL_PROJECT_PERCENT,
)

# Prize funding patterns for fallback detection
_PRIZE_PAT = re.compile(
    r"(share of (?:a |an )?£\s*([\d,.]+)\s*(?:m|million)?\s*(?:prize\s*pot|prize\s*fund))",
    flags=re.IGNORECASE
)

_PER_AWARD_PAT = re.compile(
    r"£\s*([\d,.]+)\s*(k|thousand|million|m)?\s*(?:each|per (?:winner|project|award))",
    flags=re.IGNORECASE
)


def _clean_title(raw: str) -> str:
    """
    Clean competition title by removing site prefixes and normalizing whitespace.

    Transforms:
        "Funding competition\n DRIVE35: Scale-up..."
        → "DRIVE35: Scale-up..."

    Args:
        raw: Raw title from scraper

    Returns:
        Cleaned title
    """
    if not raw:
        return raw

    # Remove "Funding competition" prefix (with optional colon/dash/newline)
    title = re.sub(
        r"^\s*Funding competition\s*[:\-]?\s*",
        "",
        raw,
        flags=re.IGNORECASE
    )

    # Collapse all whitespace (including newlines) to single spaces
    title = re.sub(r"\s+", " ", title).strip()

    return title


def _infer_prize_amount_from_text(text: str) -> Tuple[str, int]:
    """
    Extract prize funding from text using prize-specific patterns.

    Supports patterns like:
    - "share of a £1 million prize pot"
    - "£250k each"
    - "£1m per winner"

    Args:
        text: Text to search (typically description or section content)

    Returns:
        Tuple of (display_string, numeric_gbp) or (None, None)
    """
    if not text:
        return None, None

    # Priority 1: "share of a £X million prize pot"
    match = _PRIZE_PAT.search(text)
    if match:
        full_text = match.group(1)
        amount_str = match.group(2).replace(",", "")

        # Check if "million" is explicitly mentioned
        if "million" in full_text.lower() or "m" in full_text.lower():
            amount = float(amount_str) * 1_000_000
        else:
            # Assume millions for prize pots (rare to say "£1 prize pot")
            amount = float(amount_str) * 1_000_000

        return full_text, int(amount)

    # Priority 2: "£X per winner/each"
    match = _PER_AWARD_PAT.search(text)
    if match:
        amount_str = match.group(1).replace(",", "")
        magnitude = match.group(2)

        amount = float(amount_str)

        if magnitude:
            mag_lower = magnitude.lower()
            if mag_lower in ("m", "million"):
                amount *= 1_000_000
            elif mag_lower in ("k", "thousand"):
                amount *= 1_000

        return match.group(0), int(amount)

    return None, None


def apply_prize_funding_fallback(grant: Grant, scraped: ScrapedCompetition) -> Grant:
    """
    Apply prize funding fallback if standard parser failed.

    Searches description and section text for prize-style funding patterns.
    Only applies if grant currently has no funding amount.

    Args:
        grant: Grant object (possibly with null funding)
        scraped: Original scraped competition data

    Returns:
        Updated grant with prize funding if detected, otherwise unchanged
    """
    # Skip if we already have funding
    if grant.total_fund_gbp:
        return grant

    # Search description first
    display, amount = _infer_prize_amount_from_text(scraped.competition.description)

    # If not found, search section text
    if not amount:
        for section in scraped.sections:
            display, amount = _infer_prize_amount_from_text(section.text)
            if amount:
                break

    # Apply if found
    if amount:
        grant.total_fund = display
        grant.total_fund_gbp = amount

    return grant


def normalize_scraped_competition(
    scraped: ScrapedCompetition,
    documents: List[Document],
) -> Tuple[Grant, List[IndexableDocument]]:
    """
    Convert ScrapedCompetition + Documents into canonical domain models.

    Includes:
    - Competition type detection (grant/loan/prize)
    - Per-project funding extraction
    - Expected winners calculation

    Args:
        scraped: Raw scraped competition data
        documents: Fetched documents from resources

    Returns:
        Tuple of (Grant, List[IndexableDocument])
    """
    comp = scraped.competition

    # Parse funding amount
    raw_total_fund = comp.total_fund or ""
    total_fund_display, total_fund_gbp = parse_gbp_amount(raw_total_fund)

    # Parse per-project funding from project_size
    project_funding_min, project_funding_max = _parse_project_funding(comp.project_size)

    # Calculate expected winners
    expected_winners = _calculate_expected_winners(
        total_fund_gbp, project_funding_min, project_funding_max
    )

    # Detect competition type
    title = _clean_title(comp.title)
    description = comp.description or ""
    competition_type = _detect_competition_type(title, description)

    # 1. Create canonical Grant
    grant = Grant(
        id=f"innovate_uk_{comp.id}",
        source="innovate_uk",
        external_id=comp.external_id,
        title=title,
        description=description,
        url=comp.base_url,
        opens_at=comp.opens_at,
        closes_at=comp.closes_at,
        is_active=_infer_is_active(comp.opens_at, comp.closes_at),
        total_fund=total_fund_display,
        total_fund_gbp=total_fund_gbp,
        project_size=comp.project_size,
        project_funding_min=project_funding_min,
        project_funding_max=project_funding_max,
        expected_winners=expected_winners,
        competition_type=competition_type,
        funding_rules=comp.funding_rules,
        tags=_extract_tags(comp),
        scraped_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    # 2. Create IndexableDocuments
    indexable_docs: List[IndexableDocument] = []

    # 2a. Sections → IndexableDocuments
    for section in scraped.sections:
        doc_id = f"{grant.id}_section_{section.name}"
        indexable_docs.append(
            IndexableDocument(
                id=doc_id,
                grant_id=grant.id,
                doc_type="competition_section",
                section_name=section.name,
                text=section.text,
                source_url=section.url,
                citation_text=f"{comp.title} - {section.name.title()} Section",
                chunk_index=0,
                total_chunks=1,
            )
        )

    # 2b. Documents (PDFs + guidance) → IndexableDocuments
    for doc in documents:
        doc_id = f"{grant.id}_doc_{doc.id}"

        # Determine section name if it's competition-specific
        section_name = None
        if doc.competition_id:
            # Try to infer section from resource title/type
            if doc.doc_type == "briefing_pdf":
                section_name = "briefing"
            else:
                section_name = "supporting_information"

        # Determine scope (competition-specific or global)
        scope = "competition" if doc.competition_id else "global"

        # Build citation text
        resource = next((r for r in scraped.resources if r.id == doc.resource_id), None)
        citation_text = resource.title if resource else doc.source_url

        indexable_docs.append(
            IndexableDocument(
                id=doc_id,
                grant_id=grant.id,
                doc_type=doc.doc_type,
                text=doc.text,
                source_url=doc.source_url,
                resource_id=doc.resource_id,
                section_name=section_name,
                citation_text=f"{comp.title} - {citation_text}",
                scope=scope,
                chunk_index=0,
                total_chunks=1,
            )
        )

    # Apply prize funding fallback if standard parser didn't capture funding
    grant = apply_prize_funding_fallback(grant, scraped)

    return grant, indexable_docs


def _detect_competition_type(title: str, description: str) -> str:
    """
    Detect if competition is grant, loan, or prize.

    Args:
        title: Competition title
        description: Competition description

    Returns:
        Competition type: "grant", "loan", or "prize"
    """
    title_lower = title.lower()
    desc_lower = description.lower()

    # Check for loan indicators
    loan_indicators = [
        "loan" in title_lower,
        "innovation loan" in desc_lower,
        "loans for" in desc_lower,
        "loan funding" in desc_lower,
    ]
    if any(loan_indicators):
        return COMPETITION_TYPE_LOAN

    # Check for prize indicators
    prize_indicators = [
        "prize" in title_lower,
        "challenge prize" in desc_lower,
        "prize pot" in desc_lower,
        "prize fund" in desc_lower,
        "prize competition" in desc_lower,
    ]
    if any(prize_indicators):
        return COMPETITION_TYPE_PRIZE

    # Default to grant
    return COMPETITION_TYPE_GRANT


def _parse_project_funding(project_size: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """
    Parse per-project funding amounts from project_size string.

    Handles formats:
    - "£150,000 to £750,000"
    - "between £200,000 and £500,000"
    - "up to £600,000"
    - "total eligible costs can be up to £4 million"
    - "grant funding request must not exceed £2 million"

    Args:
        project_size: Project size string

    Returns:
        Tuple of (min_amount, max_amount) in GBP
    """
    if not project_size:
        return None, None

    # Normalize text
    text = project_size.lower()

    # Pattern 1: Range with "to" or "and" - "£X to £Y"
    range_pattern = r'£\s*([\d,]+(?:\.\d+)?)\s*([km])?\s*(?:to|and|-)\s*£\s*([\d,]+(?:\.\d+)?)\s*([km]|million|thousand)?'
    match = re.search(range_pattern, text, re.IGNORECASE)
    if match:
        min_str = match.group(1).replace(',', '')
        min_mag = match.group(2) or ''
        max_str = match.group(3).replace(',', '')
        max_mag = match.group(4) or ''

        try:
            min_amount = float(min_str)
            max_amount = float(max_str)

            # Apply magnitude to min
            if 'm' in min_mag.lower() or 'million' in min_mag.lower():
                min_amount *= 1_000_000
            elif 'k' in min_mag.lower() or 'thousand' in min_mag.lower():
                min_amount *= 1_000

            # Apply magnitude to max
            if 'm' in max_mag.lower() or 'million' in max_mag.lower():
                max_amount *= 1_000_000
            elif 'k' in max_mag.lower() or 'thousand' in max_mag.lower():
                max_amount *= 1_000

            return int(min_amount), int(max_amount)
        except (ValueError, IndexError):
            pass

    # Pattern 2: "between £X and £Y" (alternative phrasing)
    between_pattern = r'between £\s*([\d,]+(?:\.\d+)?)\s*([km]|million|thousand)?\s*and £\s*([\d,]+(?:\.\d+)?)\s*([km]|million|thousand)?'
    match = re.search(between_pattern, text, re.IGNORECASE)
    if match:
        min_str = match.group(1).replace(',', '')
        min_mag = (match.group(2) or '').lower()
        max_str = match.group(3).replace(',', '')
        max_mag = (match.group(4) or '').lower()

        try:
            min_amount = float(min_str)
            max_amount = float(max_str)

            # Apply magnitudes
            if 'm' in min_mag or 'million' in min_mag:
                min_amount *= 1_000_000
            elif 'k' in min_mag or 'thousand' in min_mag:
                min_amount *= 1_000

            if 'm' in max_mag or 'million' in max_mag:
                max_amount *= 1_000_000
            elif 'k' in max_mag or 'thousand' in max_mag:
                max_amount *= 1_000

            return int(min_amount), int(max_amount)
        except ValueError:
            pass

    # Pattern 3: "up to £X" or "not exceed £X" (only max)
    max_patterns = [
        r'up to £\s*([\d,]+(?:\.\d+)?)\s*(k|m|million|thousand)?',
        r'not exceed £\s*([\d,]+(?:\.\d+)?)\s*(k|m|million|thousand)?',
        r'maximum.*?£\s*([\d,]+(?:\.\d+)?)\s*(k|m|million|thousand)?',
        r'can apply for £\s*([\d,]+(?:\.\d+)?)\s*(k|m|million|thousand)?',
        r'request.*?£\s*([\d,]+(?:\.\d+)?)\s*(k|m|million|thousand)?',
    ]

    for pattern in max_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            max_str = match.group(1).replace(',', '')
            mag_str = (match.group(2) or '').lower()

            try:
                max_amount = float(max_str)

                if 'm' in mag_str or 'million' in mag_str:
                    max_amount *= 1_000_000
                elif 'k' in mag_str or 'thousand' in mag_str:
                    max_amount *= 1_000

                return None, int(max_amount)
            except ValueError:
                pass

    # Pattern 4: Plain amount like "£600,000" (when it's the only amount mentioned)
    plain_amount_pattern = r'£\s*([\d,]+(?:\.\d+)?)\s*(k|m|million|thousand)?'
    matches = re.findall(plain_amount_pattern, text, re.IGNORECASE)
    if matches and len(matches) == 1:
        # Only one amount mentioned, treat as max
        amount_str = matches[0][0].replace(',', '')
        mag_str = (matches[0][1] or '').lower()

        try:
            amount = float(amount_str)

            if 'm' in mag_str or 'million' in mag_str:
                amount *= 1_000_000
            elif 'k' in mag_str or 'thousand' in mag_str:
                amount *= 1_000

            return None, int(amount)
        except ValueError:
            pass

    return None, None


def _calculate_expected_winners(
    total_fund_gbp: Optional[int],
    project_min: Optional[int],
    project_max: Optional[int],
) -> Optional[int]:
    """
    Calculate expected number of winners.

    Uses 70% of max project funding as typical project size (per SME feedback).

    Args:
        total_fund_gbp: Total funding pot in GBP
        project_min: Minimum per-project funding in GBP
        project_max: Maximum per-project funding in GBP

    Returns:
        Expected number of winners or None if calculation not possible
    """
    if not total_fund_gbp or not project_max:
        return None

    # Use 70% heuristic per SME feedback
    typical_project = int(project_max * TYPICAL_PROJECT_PERCENT)
    if typical_project <= 0:
        return None

    return total_fund_gbp // typical_project


def _infer_is_active(opens_at, closes_at) -> bool:
    """
    Infer if competition is currently active using London local time.

    Uses timezone-aware comparison with Europe/London timezone to correctly
    handle BST ↔ GMT transitions and match official grant deadlines.

    Active if:
    - Opens in the past (or no open date)
    - Closes in the future (or no close date)
    """
    status = infer_status(opens_at, closes_at)
    return status == "active"


def _extract_tags(comp) -> List[str]:
    """
    Extract searchable tags from competition metadata.

    Tags help with filtering and categorization.
    """
    tags = ["innovate_uk"]

    # Add funding level tags
    if comp.total_fund:
        fund_lower = comp.total_fund.lower()
        if "million" in fund_lower:
            tags.append("large_fund")
        elif "thousand" in fund_lower:
            tags.append("small_fund")

    # Add project size tags
    if comp.project_size:
        size_lower = comp.project_size.lower()
        if "million" in size_lower:
            tags.append("large_project")
        elif "thousand" in size_lower:
            tags.append("small_project")

    # Add status tags
    if comp.opens_at and comp.closes_at:
        tags.append("dated")
    else:
        tags.append("rolling")

    return tags
