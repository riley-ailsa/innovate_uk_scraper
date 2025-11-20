"""
Container types for scraped data.
"""

from dataclasses import dataclass
from typing import List
from src.core.models import Competition, CompetitionSection, SupportingResource


@dataclass
class ScrapedCompetition:
    """
    Container for all data scraped from a single competition page.

    This is the return type of InnovateUKCompetitionScraper.scrape_competition().

    Attributes:
        competition: The competition metadata
        sections: List of page sections with fragment URLs
        resources: List of supporting resources (PDFs, videos, etc.)
    """
    competition: Competition
    sections: List[CompetitionSection]
    resources: List[SupportingResource]

    def __repr__(self) -> str:
        return (
            f"ScrapedCompetition("
            f"competition={self.competition.title}, "
            f"sections={len(self.sections)}, "
            f"resources={len(self.resources)})"
        )
