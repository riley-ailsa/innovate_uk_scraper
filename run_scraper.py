"""
Normalization functions for Innovate UK scraper output.

Converts ScrapedCompetition objects into canonical domain models:
- Grant (canonical competition)
- IndexableDocument (sections + resources)
"""

import re
from datetime import datetime
from typing import List, Tuple

from src.core.domain_models import Grant, IndexableDocument
from src.ingest.innovatuk_types import ScrapedCompetition
from src.core.models import Document
from src.core.money import parse_gbp_amount
from src.core.time_utils import infer_status

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

    # 1. Create canonical Grant
    grant = Grant(
        id=f"innovate_uk_{comp.id}",
        source="innovate_uk",
        external_id=comp.external_id,
        title=_clean_title(comp.title),
        description=comp.description or "",
        url=comp.base_url,
        opens_at=comp.opens_at,
        closes_at=comp.closes_at,
        is_active=_infer_is_active(comp.opens_at, comp.closes_at),
        total_fund=total_fund_display,
        total_fund_gbp=total_fund_gbp,
        project_size=comp.project_size,
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
