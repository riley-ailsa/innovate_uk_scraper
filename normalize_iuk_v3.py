"""
Innovate UK v3 Normalizer

Converts ScrapedCompetition into ailsa_shared Grant schema with
9 independently embeddable sections for RAG.

Section mapping:
    IUK Section              → v3 Section
    ─────────────────────────────────────────
    summary                  → summary.text
    eligibility              → eligibility.text
    scope                    → scope.text
    dates                    → dates.key_dates_text
    how-to-apply             → how_to_apply.text
    supporting-information   → supporting_info.text
    (metadata)               → funding
    (extracted)              → assessment, contacts
"""

import re
import logging
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import replace

from ailsa_shared.models import (
    Grant,
    GrantSource,
    GrantStatus,
    GrantSections,
    SummarySection,
    EligibilitySection,
    ScopeSection,
    DatesSection,
    FundingSection,
    HowToApplySection,
    AssessmentSection,
    SupportingInfoSection,
    ContactsSection,
    SupportingDocument,
    Contact,
    ProgrammeInfo,
    ProcessingInfo,
    CompetitionType,
)

from src.ingest.innovatuk_types import ScrapedCompetition
from src.core.models import CompetitionSection, SupportingResource, ResourceType

logger = logging.getLogger(__name__)


# =============================================================================
# MAIN NORMALIZER
# =============================================================================

def normalize_iuk_v3(scraped: ScrapedCompetition) -> Grant:
    """
    Normalize IUK ScrapedCompetition to v3 Grant schema.
    
    Args:
        scraped: ScrapedCompetition from IUK scraper
        
    Returns:
        Grant with all sections populated
    """
    comp = scraped.competition
    sections = {s.name: s for s in scraped.sections}
    
    # Build grant_id
    grant_id = f"iuk_{comp.external_id}" if comp.external_id else f"iuk_{comp.id}"
    
    # Clean title
    title = _clean_title(comp.title)
    
    # Determine status
    status = _infer_status(comp.opens_at, comp.closes_at)
    is_active = status == GrantStatus.OPEN
    
    # Build URL (strip fragment)
    url = comp.base_url.split('#')[0] if comp.base_url else ""
    
    # Parse funding
    total_pot_gbp, total_pot_display = _parse_funding_amount(comp.total_fund)
    per_project_min, per_project_max, per_project_display = _parse_project_funding(comp.project_size)
    
    # Fallback: search section text for per-project funding if not in metadata
    if not per_project_display:
        all_section_text = " ".join(s.text for s in scraped.sections if s.text)
        per_project_min, per_project_max, per_project_display = _extract_per_project_from_text(all_section_text)
    
    # Detect competition type
    competition_type = _detect_competition_type(title, comp.description or "")
    
    # Build sections
    grant_sections = GrantSections(
        summary=_build_summary_section(sections.get('summary'), title),
        eligibility=_build_eligibility_section(sections.get('eligibility'), comp.funding_rules),
        scope=_build_scope_section(sections.get('scope'), title),
        dates=_build_dates_section(sections.get('dates'), comp.opens_at, comp.closes_at),
        funding=_build_funding_section(
            total_pot_gbp, total_pot_display,
            per_project_min, per_project_max, per_project_display,
            comp.funding_rules, competition_type
        ),
        how_to_apply=_build_how_to_apply_section(sections.get('how-to-apply')),
        assessment=_build_assessment_section(sections.get('how-to-apply'), sections.get('eligibility')),
        supporting_info=_build_supporting_info_section(
            sections.get('supporting-information'),
            scraped.resources
        ),
        contacts=_build_contacts_section(sections, scraped.resources),
    )
    
    # Build programme info
    programme = _build_programme_info(title, comp.external_id)
    
    # Build tags
    tags = _build_tags(title, competition_type, total_pot_gbp, per_project_max, status)
    
    # Create Grant
    grant = Grant(
        grant_id=grant_id,
        source=GrantSource.INNOVATE_UK,
        external_id=comp.external_id,
        title=title,
        url=url,
        status=status,
        is_active=is_active,
        sections=grant_sections,
        programme=programme,
        tags=tags,
        raw=None,  # Can store comp.__dict__ if needed
        processing=ProcessingInfo(
            scraped_at=datetime.utcnow(),
            normalized_at=datetime.utcnow(),
            sections_extracted=list(sections.keys()),
            schema_version="3.0",
        ),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    
    return grant


# =============================================================================
# SECTION BUILDERS
# =============================================================================

def _build_summary_section(section: Optional[CompetitionSection], title: str) -> SummarySection:
    """Build summary section from IUK summary."""
    text = section.text if section else ""
    
    return SummarySection(
        text=text,
        html=section.html if section else None,
        extracted_at=datetime.utcnow(),
    )


def _build_eligibility_section(
    section: Optional[CompetitionSection],
    funding_rules: Dict[str, Any]
) -> EligibilitySection:
    """Build eligibility section with parsed who_can_apply."""
    text = section.text if section else ""
    
    # Extract who can apply from text
    who_can_apply = _extract_who_can_apply(text)
    
    # Extract organisation types from funding rules
    org_types = list(funding_rules.keys()) if funding_rules else []
    
    # Check partnership requirements
    partnership_required = _check_partnership_required(text)
    partnership_details = _extract_partnership_details(text)
    
    # Check UK registration
    uk_required = _check_uk_required(text)
    
    # Geographic scope
    geographic_scope = _infer_geographic_scope(text)
    
    return EligibilitySection(
        text=text,
        who_can_apply=who_can_apply,
        organisation_type=org_types,
        uk_registered_required=uk_required,
        geographic_scope=geographic_scope,
        partnership_required=partnership_required,
        partnership_details=partnership_details,
        extracted_at=datetime.utcnow(),
    )


def _build_scope_section(section: Optional[CompetitionSection], title: str) -> ScopeSection:
    """Build scope section with theme extraction."""
    text = section.text if section else ""
    
    # Extract themes from title and text
    themes = _extract_themes(title, text)
    
    # Extract sectors
    sectors = _extract_sectors(text)
    
    # Extract TRL
    trl_min, trl_max, trl_range = _extract_trl(text)
    
    return ScopeSection(
        text=text,
        themes=themes,
        sectors=sectors,
        trl_min=trl_min,
        trl_max=trl_max,
        trl_range=trl_range,
        extracted_at=datetime.utcnow(),
    )


def _build_dates_section(
    section: Optional[CompetitionSection],
    opens_at: Optional[datetime],
    closes_at: Optional[datetime]
) -> DatesSection:
    """Build dates section."""
    text = section.text if section else ""
    
    # Extract deadline time
    deadline_time = _extract_deadline_time(text, closes_at)
    
    # Extract project duration
    duration_min, duration_max, duration_text = _extract_project_duration(text)
    
    return DatesSection(
        opens_at=opens_at,
        closes_at=closes_at,
        deadline_time=deadline_time,
        timezone="Europe/London",
        project_duration=duration_text,
        project_duration_months_min=duration_min,
        project_duration_months_max=duration_max,
        key_dates_text=text,
        extracted_at=datetime.utcnow(),
    )


def _build_funding_section(
    total_pot_gbp: Optional[int],
    total_pot_display: Optional[str],
    per_project_min: Optional[int],
    per_project_max: Optional[int],
    per_project_display: Optional[str],
    funding_rules: Dict[str, Any],
    competition_type: CompetitionType
) -> FundingSection:
    """Build funding section."""
    # Build funding rate text
    funding_rate = None
    if funding_rules:
        rates = [f"{k}: {v}%" for k, v in funding_rules.items()]
        funding_rate = ", ".join(rates)
    
    # Build text summary
    text_parts = []
    if total_pot_display:
        text_parts.append(f"Total: {total_pot_display}")
    if per_project_display:
        text_parts.append(f"Per project: {per_project_display}")
    if funding_rate:
        text_parts.append(f"Rates: {funding_rate}")
    
    return FundingSection(
        text=". ".join(text_parts) if text_parts else None,
        total_pot_gbp=total_pot_gbp,
        total_pot_display=total_pot_display,
        currency="GBP",
        per_project_min_gbp=per_project_min,
        per_project_max_gbp=per_project_max,
        per_project_display=per_project_display,
        funding_rate=funding_rate,
        funding_rate_by_org_type=funding_rules if funding_rules else None,
        competition_type=competition_type,
        extracted_at=datetime.utcnow(),
    )


def _build_how_to_apply_section(section: Optional[CompetitionSection]) -> HowToApplySection:
    """Build how to apply section."""
    text = section.text if section else ""
    
    # Extract application URL
    apply_url = _extract_apply_url(text)
    
    return HowToApplySection(
        text=text,
        portal_name="Innovation Funding Service",
        portal_url="https://apply-for-innovation-funding.service.gov.uk",
        apply_url=apply_url,
        registration_required=True,
        extracted_at=datetime.utcnow(),
    )


def _build_assessment_section(
    how_to_apply: Optional[CompetitionSection],
    eligibility: Optional[CompetitionSection]
) -> AssessmentSection:
    """Build assessment section from how-to-apply content."""
    # IUK assessment criteria are usually in how-to-apply
    text = ""
    criteria = []
    
    if how_to_apply:
        # Look for assessment/criteria content
        assessment_text = _extract_assessment_text(how_to_apply.text)
        if assessment_text:
            text = assessment_text
        
        # Extract criteria
        criteria = _extract_assessment_criteria(how_to_apply.text)
    
    return AssessmentSection(
        text=text,
        criteria=criteria,
        extracted_at=datetime.utcnow(),
    )


def _build_supporting_info_section(
    section: Optional[CompetitionSection],
    resources: List[SupportingResource]
) -> SupportingInfoSection:
    """Build supporting info section with documents."""
    text = section.text if section else ""
    
    # Convert resources to SupportingDocument
    documents = []
    for r in resources:
        doc_type = r.type.value if r.type else None
        documents.append(SupportingDocument(
            title=r.title or "Untitled",
            url=r.url,
            type=doc_type,
        ))
    
    return SupportingInfoSection(
        text=text,
        documents=documents,
        extracted_at=datetime.utcnow(),
    )


def _build_contacts_section(
    sections: Dict[str, CompetitionSection],
    resources: List[SupportingResource]
) -> ContactsSection:
    """Build contacts section by extracting emails."""
    # Search all section text for emails
    all_text = " ".join(s.text for s in sections.values() if s.text)
    
    emails = _extract_emails(all_text)
    
    contacts = []
    for email in emails:
        contacts.append(Contact(email=email))
    
    # IUK default helpdesk
    helpdesk_email = "support@iuk.ukri.org"
    
    return ContactsSection(
        contacts=contacts,
        helpdesk_email=helpdesk_email,
        helpdesk_url="https://apply-for-innovation-funding.service.gov.uk/info/contact",
        extracted_at=datetime.utcnow(),
    )


def _build_programme_info(title: str, external_id: str) -> ProgrammeInfo:
    """Build programme info from title."""
    programme_name = _infer_programme_name(title)
    
    return ProgrammeInfo(
        name=programme_name,
        funder="UKRI / Innovate UK",
        competition_code=external_id,
    )


# =============================================================================
# PARSING HELPERS
# =============================================================================

def _clean_title(raw: str) -> str:
    """Clean competition title."""
    if not raw:
        return raw
    
    # Remove "Funding competition" prefix
    title = re.sub(
        r"^\s*Funding competition\s*[:\-]?\s*",
        "",
        raw,
        flags=re.IGNORECASE
    )
    
    # Collapse whitespace
    title = re.sub(r"\s+", " ", title).strip()
    
    return title


def _infer_status(opens_at: Optional[datetime], closes_at: Optional[datetime]) -> GrantStatus:
    """Infer grant status from dates."""
    now = datetime.utcnow()
    
    if closes_at and closes_at < now:
        return GrantStatus.CLOSED
    
    if opens_at and opens_at > now:
        return GrantStatus.FORTHCOMING
    
    if opens_at and closes_at:
        if opens_at <= now <= closes_at:
            return GrantStatus.OPEN
    
    # Default to open if we have no dates but it's on the site
    return GrantStatus.OPEN


def _parse_funding_amount(raw: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    """Parse total funding amount."""
    if not raw:
        return None, None
    
    display = raw.strip()
    
    # Pattern: £X million, £X,XXX, up to £X
    pattern = r'£\s*([\d,]+(?:\.\d+)?)\s*(million|m|thousand|k)?'
    match = re.search(pattern, raw, re.IGNORECASE)
    
    if not match:
        return None, display
    
    amount_str = match.group(1).replace(',', '')
    magnitude = (match.group(2) or '').lower()
    
    try:
        amount = float(amount_str)
        
        if magnitude in ('million', 'm'):
            amount *= 1_000_000
        elif magnitude in ('thousand', 'k'):
            amount *= 1_000
        
        return int(amount), display
    except ValueError:
        return None, display


def _parse_project_funding(raw: Optional[str]) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """Parse per-project funding range from project_size field."""
    if not raw:
        return None, None, None
    
    return _extract_per_project_from_text(raw)


def _extract_per_project_from_text(text: str) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """
    Extract per-project funding from any text (section content or project_size field).
    Handles magnitudes like 'million', 'm', 'k'.
    """
    if not text:
        return None, None, None
    
    patterns = [
        # between £X (million) and £Y (million)
        (r'between\s*£([\d,]+(?:\.\d+)?)\s*(million|m|k)?\s*and\s*£([\d,]+(?:\.\d+)?)\s*(million|m|k)?', 'range'),
        # eligible costs between £X and £Y
        (r'eligible costs.*?between\s*£([\d,]+(?:\.\d+)?)\s*(million|m|k)?\s*and\s*£([\d,]+(?:\.\d+)?)\s*(million|m|k)?', 'range'),
        # total costs of £X to £Y
        (r'total.*?costs.*?£([\d,]+(?:\.\d+)?)\s*(million|m|k)?\s*(?:to|and|-)\s*£([\d,]+(?:\.\d+)?)\s*(million|m|k)?', 'range'),
        # £X (million) to £Y (million)
        (r'£([\d,]+(?:\.\d+)?)\s*(million|m|k)?\s*(?:to|-)\s*£([\d,]+(?:\.\d+)?)\s*(million|m|k)?', 'range'),
        # up to £X (million) per project/each/award
        (r'up to £([\d,]+(?:\.\d+)?)\s*(million|m|k)?\s*(?:per project|each project|for each|per award|each)', 'max'),
        # can apply for up to £X
        (r'can apply for.*?up to £([\d,]+(?:\.\d+)?)\s*(million|m|k)?', 'max'),
    ]
    
    def apply_magnitude(val_str, mag):
        val = float(val_str.replace(',', ''))
        mag = (mag or '').lower()
        if mag in ('m', 'million'):
            val *= 1_000_000
        elif mag == 'k':
            val *= 1_000
        return int(val)
    
    def format_amount(val):
        if val >= 1_000_000:
            formatted = f"£{val/1_000_000:.1f}m"
            return formatted.replace('.0m', 'm')
        elif val >= 1_000:
            return f"£{val:,}"
        return f"£{val}"
    
    for pattern, ptype in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if ptype == 'range':
                min_val = apply_magnitude(match.group(1), match.group(2))
                max_val = apply_magnitude(match.group(3), match.group(4))
                display = f"{format_amount(min_val)} to {format_amount(max_val)}"
                return min_val, max_val, display
            elif ptype == 'max':
                max_val = apply_magnitude(match.group(1), match.group(2))
                return None, max_val, f"up to {format_amount(max_val)}"
    
    return None, None, None


def _detect_competition_type(title: str, description: str) -> CompetitionType:
    """Detect if competition is grant, loan, or prize."""
    title_lower = title.lower()
    desc_lower = description.lower()
    
    if 'loan' in title_lower or 'innovation loan' in desc_lower:
        return CompetitionType.LOAN
    
    if 'prize' in title_lower or 'prize pot' in desc_lower:
        return CompetitionType.PRIZE
    
    return CompetitionType.GRANT


# =============================================================================
# EXTRACTION HELPERS
# =============================================================================

def _extract_who_can_apply(text: str) -> List[str]:
    """Extract who can apply from eligibility text."""
    who = []
    text_lower = text.lower()
    
    patterns = [
        (r'\bsme\b', 'SME'),
        (r'\bsmall.*medium.*enterprise', 'SME'),
        (r'\bacademic', 'Academic institution'),
        (r'\buniversit', 'University'),
        (r'\brto\b', 'RTO'),
        (r'\bresearch.*organisation', 'Research organisation'),
        (r'\bcatapult', 'Catapult'),
        (r'\bcharity', 'Charity'),
        (r'\bnhs\b', 'NHS organisation'),
        (r'\bpublic sector', 'Public sector'),
        (r'\blarge.*business', 'Large business'),
        (r'\bmicro.*business', 'Micro business'),
        (r'\bstart-?up', 'Start-up'),
    ]
    
    for pattern, label in patterns:
        if re.search(pattern, text_lower):
            if label not in who:
                who.append(label)
    
    return who


def _check_partnership_required(text: str) -> Optional[bool]:
    """Check if partnership is required."""
    text_lower = text.lower()
    
    if 'must include' in text_lower and 'partner' in text_lower:
        return True
    if 'collaborative' in text_lower and 'required' in text_lower:
        return True
    if 'consortium' in text_lower:
        return True
    if 'single applicant' in text_lower or 'single organisation' in text_lower:
        return False
    
    return None


def _extract_partnership_details(text: str) -> Optional[str]:
    """Extract partnership requirements details."""
    # Look for sentences about partnerships
    sentences = text.split('.')
    for s in sentences:
        s_lower = s.lower()
        if 'partner' in s_lower and any(w in s_lower for w in ['must', 'require', 'need', 'include']):
            return s.strip() + '.'
    return None


def _check_uk_required(text: str) -> Optional[bool]:
    """Check if UK registration is required."""
    text_lower = text.lower()
    
    if 'uk registered' in text_lower or 'registered in the uk' in text_lower:
        return True
    if 'uk-based' in text_lower or 'based in the uk' in text_lower:
        return True
    
    return None


def _infer_geographic_scope(text: str) -> Optional[str]:
    """Infer geographic scope from text."""
    text_lower = text.lower()
    
    if 'uk only' in text_lower or 'uk-only' in text_lower:
        return "UK only"
    if 'international' in text_lower:
        return "International"
    if 'eu partner' in text_lower or 'european' in text_lower:
        return "UK + EU"
    
    return "UK"  # Default for IUK


def _extract_themes(title: str, text: str) -> List[str]:
    """Extract themes from title and text."""
    themes = []
    combined = (title + " " + text).lower()
    
    theme_patterns = [
        (r'\bai\b|artificial intelligence|machine learning', 'AI & Machine Learning'),
        (r'\bnet zero\b|decarboni|climate|green', 'Net Zero & Climate'),
        (r'\bhealth|medical|pharma|life science', 'Health & Life Sciences'),
        (r'\bagricultur|farm|food', 'Agriculture & Food'),
        (r'\bmanufactur|industr', 'Manufacturing'),
        (r'\baerospace|aviation|space', 'Aerospace & Space'),
        (r'\bautomoti|vehicle|ev\b|electric vehicle', 'Automotive'),
        (r'\benergy|battery|hydrogen', 'Energy'),
        (r'\bdigital|cyber|software', 'Digital & Cyber'),
        (r'\bdefence|defense|security', 'Defence & Security'),
        (r'\bcreative|media|gaming', 'Creative Industries'),
        (r'\bfintech|financial technology', 'FinTech'),
        (r'\bquantum', 'Quantum'),
        (r'\bsemiconduct|chip', 'Semiconductors'),
        (r'\brobot|automat', 'Robotics & Automation'),
    ]
    
    for pattern, label in theme_patterns:
        if re.search(pattern, combined):
            if label not in themes:
                themes.append(label)
    
    return themes


def _extract_sectors(text: str) -> List[str]:
    """Extract sectors from text."""
    sectors = []
    text_lower = text.lower()
    
    sector_patterns = [
        (r'\bhealthcare|nhs\b', 'Healthcare'),
        (r'\btransport|logistics', 'Transport & Logistics'),
        (r'\bconstruction|built environment', 'Construction'),
        (r'\bretail|consumer', 'Retail & Consumer'),
        (r'\bfinancial services|banking', 'Financial Services'),
        (r'\beducation|edtech', 'Education'),
        (r'\benvironmental|water|waste', 'Environmental'),
        (r'\btelecommunication', 'Telecommunications'),
    ]
    
    for pattern, label in sector_patterns:
        if re.search(pattern, text_lower):
            if label not in sectors:
                sectors.append(label)
    
    return sectors


def _extract_trl(text: str) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """Extract TRL range from text."""
    # Pattern: TRL X-Y or TRL X to Y
    pattern = r'trl\s*(\d)\s*[-–to]+\s*(\d)'
    match = re.search(pattern, text.lower())
    
    if match:
        trl_min = int(match.group(1))
        trl_max = int(match.group(2))
        return trl_min, trl_max, f"TRL {trl_min}-{trl_max}"
    
    # Single TRL
    pattern = r'trl\s*(\d)'
    match = re.search(pattern, text.lower())
    
    if match:
        trl = int(match.group(1))
        return trl, trl, f"TRL {trl}"
    
    return None, None, None


def _extract_deadline_time(text: str, closes_at: Optional[datetime]) -> Optional[str]:
    """Extract deadline time from text."""
    # Pattern: 11:00, 11:00am, 11am
    pattern = r'\b(\d{1,2}):?(\d{2})?\s*(am|pm)?\b'
    match = re.search(pattern, text.lower())
    
    if match:
        hour = match.group(1)
        mins = match.group(2) or '00'
        ampm = match.group(3) or ''
        return f"{hour}:{mins}{ampm}".strip()
    
    # Default IUK deadline
    return "11:00am"


def _extract_project_duration(text: str) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """Extract project duration from text."""
    # Pattern: X to Y months
    pattern = r'(\d+)\s*(?:to|-)\s*(\d+)\s*months?'
    match = re.search(pattern, text.lower())
    
    if match:
        min_months = int(match.group(1))
        max_months = int(match.group(2))
        return min_months, max_months, f"{min_months}-{max_months} months"
    
    # Pattern: up to X months
    pattern = r'up to\s*(\d+)\s*months?'
    match = re.search(pattern, text.lower())
    
    if match:
        max_months = int(match.group(1))
        return None, max_months, f"up to {max_months} months"
    
    # Pattern: X months
    pattern = r'(\d+)\s*months?'
    match = re.search(pattern, text.lower())
    
    if match:
        months = int(match.group(1))
        return months, months, f"{months} months"
    
    return None, None, None


def _extract_apply_url(text: str) -> Optional[str]:
    """Extract application URL from text."""
    # Look for IUK application links
    pattern = r'https://apply-for-innovation-funding\.service\.gov\.uk/[^\s<>"\']*'
    match = re.search(pattern, text)
    
    if match:
        return match.group(0)
    
    return None


def _extract_assessment_text(text: str) -> Optional[str]:
    """Extract assessment criteria text from how-to-apply section."""
    # Look for assessment/criteria section
    patterns = [
        r'(assessment.*?criteria.*?(?:\n\n|\Z))',
        r'(how.*?assess.*?(?:\n\n|\Z))',
        r'(scoring.*?criteria.*?(?:\n\n|\Z))',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    
    return None


def _extract_assessment_criteria(text: str) -> List[str]:
    """Extract assessment criteria from text."""
    criteria = []
    text_lower = text.lower()
    
    # Common IUK criteria
    criteria_patterns = [
        (r'\binnovation\b', 'Innovation'),
        (r'\bimpact\b', 'Impact'),
        (r'\bdeliverability\b', 'Deliverability'),
        (r'\bvalue for money\b', 'Value for money'),
        (r'\bteam\b.*\bcapability\b', 'Team capability'),
        (r'\bexploitation\b', 'Exploitation'),
        (r'\brisk\b', 'Risk management'),
        (r'\bmarket\b', 'Market opportunity'),
    ]
    
    for pattern, label in criteria_patterns:
        if re.search(pattern, text_lower):
            if label not in criteria:
                criteria.append(label)
    
    return criteria


def _extract_emails(text: str) -> List[str]:
    """Extract email addresses from text."""
    pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(pattern, text)
    
    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for email in emails:
        email_lower = email.lower()
        if email_lower not in seen:
            seen.add(email_lower)
            unique.append(email)
    
    return unique


def _infer_programme_name(title: str) -> Optional[str]:
    """Infer programme name from title."""
    title_lower = title.lower()
    
    programmes = [
        ('ktp', 'Knowledge Transfer Partnership'),
        ('knowledge transfer partnership', 'Knowledge Transfer Partnership'),
        ('catapult', 'Catapult Network'),
        ('smart grant', 'SMART Grants'),
        ('smart:', 'SMART Grants'),
        ('farming innovation', 'Farming Innovation Programme'),
        ('biomedical catalyst', 'Biomedical Catalyst'),
        ('future leaders fellowship', 'Future Leaders Fellowship'),
        ('strength in places', 'Strength in Places'),
        ('launchpad', 'Launchpad'),
        ('innovation loan', 'Innovation Loans'),
        ('sbri', 'SBRI'),
        ('horizon europe guarantee', 'Horizon Europe Guarantee'),
        ('eureka', 'Eureka'),
        ('eurostars', 'Eurostars'),
        ('globalstars', 'Globalstars'),
    ]
    
    for pattern, name in programmes:
        if pattern in title_lower:
            return name
    
    return None


def _build_tags(
    title: str,
    competition_type: CompetitionType,
    total_pot_gbp: Optional[int],
    per_project_max: Optional[int],
    status: GrantStatus
) -> List[str]:
    """Build tags for filtering."""
    tags = ["innovate_uk"]
    
    # Competition type
    tags.append(competition_type.value)
    
    # Status
    tags.append(status.value)
    
    # Funding size tags
    if total_pot_gbp:
        if total_pot_gbp >= 10_000_000:
            tags.append("large_fund")
        elif total_pot_gbp >= 1_000_000:
            tags.append("medium_fund")
        else:
            tags.append("small_fund")
    
    if per_project_max:
        if per_project_max >= 1_000_000:
            tags.append("large_project")
        elif per_project_max >= 100_000:
            tags.append("medium_project")
        else:
            tags.append("small_project")
    
    return tags


# =============================================================================
# BATCH PROCESSING
# =============================================================================

def normalize_iuk_batch(
    scraped_list: List[ScrapedCompetition]
) -> List[Grant]:
    """
    Normalize a batch of IUK competitions.
    
    Args:
        scraped_list: List of ScrapedCompetition objects
        
    Returns:
        List of normalized Grants
    """
    grants = []
    
    for i, scraped in enumerate(scraped_list):
        try:
            grant = normalize_iuk_v3(scraped)
            grants.append(grant)
        except Exception as e:
            logger.error(f"Failed to normalize {scraped.competition.title}: {e}")
    
    return grants


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys
    
    # Test with a single URL
    from src.ingest.innovateuk_competition import InnovateUKCompetitionScraper
    
    url = sys.argv[1] if len(sys.argv) > 1 else "https://apply-for-innovation-funding.service.gov.uk/competition/2341/overview/4b0efce9-75b8-4e84-97c0-fc6277396586"
    
    print(f"Scraping: {url}")
    scraper = InnovateUKCompetitionScraper()
    scraped = scraper.scrape_competition(url)
    
    print(f"\nNormalizing...")
    grant = normalize_iuk_v3(scraped)
    
    print(f"\n{'='*60}")
    print(f"GRANT: {grant.title}")
    print(f"{'='*60}")
    print(f"ID: {grant.grant_id}")
    print(f"Status: {grant.status.value}")
    print(f"Is Active: {grant.is_active}")
    print(f"\nSECTIONS:")
    print(f"  Summary: {len(grant.sections.summary.text)} chars")
    print(f"  Eligibility: {len(grant.sections.eligibility.text)} chars")
    print(f"  Scope: {len(grant.sections.scope.text)} chars")
    print(f"  Dates: opens={grant.sections.dates.opens_at}, closes={grant.sections.dates.closes_at}")
    print(f"  Funding: {grant.sections.funding.total_pot_display} / {grant.sections.funding.per_project_display}")
    print(f"  How to Apply: {len(grant.sections.how_to_apply.text or '')} chars")
    print(f"  Assessment: {len(grant.sections.assessment.criteria)} criteria")
    print(f"  Supporting Info: {len(grant.sections.supporting_info.documents)} docs")
    print(f"  Contacts: {grant.sections.contacts.helpdesk_email}")
    print(f"\nTags: {grant.tags}")
    print(f"Themes: {grant.sections.scope.themes}")
