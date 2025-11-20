"""
Core data models for the grant discovery system.
All models are immutable dataclasses representing scraped data.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict


@dataclass
class Competition:
    """
    Represents a single Innovate UK competition.

    Attributes:
        id: Internal stable identifier (derived from URL or external_id)
        external_id: Raw competition ID from URL (e.g., "2341")
        title: Competition title
        base_url: Main overview URL without fragments
        description: Full description text
        opens_at: Competition opening datetime (None if not found)
        closes_at: Competition closing datetime (None if not found)
        total_fund: Total funding available (e.g., "Up to £5 million")
        project_size: Project size range (e.g., "£150,000 to £750,000")
        funding_rules: Dict of funding percentages by company size
        raw_html: Full HTML of the page (for debugging/reparsing)
    """
    id: str
    external_id: str
    title: str
    base_url: str
    description: str
    opens_at: Optional[datetime] = None
    closes_at: Optional[datetime] = None
    total_fund: Optional[str] = None
    project_size: Optional[str] = None
    funding_rules: Dict[str, float] = field(default_factory=dict)
    raw_html: Optional[str] = None


@dataclass
class CompetitionSection:
    """
    Represents a logical section of a competition page.

    Each section corresponds to a fragment URL (e.g., #eligibility).

    Attributes:
        competition_id: Reference to parent competition
        name: Section name (summary|eligibility|scope|dates|how-to-apply|supporting-information)
        url: Full URL with fragment (e.g., https://example.com#eligibility)
        html: Raw HTML content of this section
        text: Cleaned text content (for vector search)
    """
    competition_id: str
    name: str
    url: str
    html: str
    text: str


class ResourceScope(str, Enum):
    """
    Scope of a supporting resource.

    GLOBAL: Generic guidance applying to many competitions
    COMPETITION: Specific to a single competition
    """
    GLOBAL = "global"
    COMPETITION = "competition"


class ResourceType(str, Enum):
    """
    Type of supporting resource.
    """
    PDF = "pdf"
    VIDEO = "video"
    WEBPAGE = "webpage"
    OTHER = "other"


@dataclass
class SupportingResource:
    """
    Represents a supporting document, video, or webpage.

    Attributes:
        id: Stable hash-based identifier
        url: Full URL to the resource
        title: Display title (from link text)
        competition_id: Set if scope is COMPETITION, None if GLOBAL
        scope: Whether this is global guidance or competition-specific
        type: Resource type (PDF, video, webpage, etc.)
        content_hash: SHA1 hash of content (set after fetching)
    """
    id: str
    url: str
    title: Optional[str]
    competition_id: Optional[str]
    scope: ResourceScope
    type: ResourceType
    content_hash: Optional[str] = None


@dataclass
class Document:
    """
    Represents extracted text content from a resource.

    Documents are the final indexed units for vector search.

    Attributes:
        id: Unique document identifier
        competition_id: Reference to competition (None for global docs)
        resource_id: Reference to source SupportingResource
        doc_type: Type of document (overview_section, briefing_pdf, guidance, etc.)
        source_url: Original URL
        text: Extracted text content
    """
    id: str
    competition_id: Optional[str]
    resource_id: Optional[str]
    doc_type: str
    source_url: str
    text: str


# Type aliases for clarity
CompetitionId = str
ResourceId = str
DocumentId = str
