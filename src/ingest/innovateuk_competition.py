"""
Scraper for Innovate UK competition pages.

This module handles:
1. Fetching HTML from competition overview URLs
2. Parsing metadata (title, dates, funding rules, project sizes)
3. Extracting sections with fragment URLs
4. Classifying supporting resources
"""

import re
import logging
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup, Tag
import certifi

from src.core.models import (
    Competition,
    CompetitionSection,
    SupportingResource,
    ResourceScope,
    ResourceType,
)
from src.core.utils import (
    stable_id_from_url,
    parse_date_maybe,
    clean_text,
    extract_money_amount,
)
from src.ingest.innovatuk_types import ScrapedCompetition


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}


class InnovateUKCompetitionScraper:
    """
    Scrapes a single Innovate UK competition overview page.

    Usage:
        scraper = InnovateUKCompetitionScraper()
        result = scraper.scrape_competition(url)
    """

    # Known section anchors in competition pages
    SECTION_ANCHORS = {
        "summary": "summary",
        "eligibility": "eligibility",
        "scope": "scope",
        "dates": "dates",
        "how-to-apply": "how-to-apply",
        "supporting-information": "supporting-information",
    }

    def __init__(self, session: Optional[requests.Session] = None):
        """
        Initialize scraper.

        Args:
            session: Optional requests.Session for connection pooling
        """
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def scrape_competition(self, overview_url: str) -> ScrapedCompetition:
        """
        Scrape a competition page and return structured data.

        Args:
            overview_url: Full URL to competition overview (without fragment)

        Returns:
            ScrapedCompetition containing competition, sections, and resources

        Raises:
            requests.HTTPError: If page fetch fails
            ValueError: If URL is invalid
        """
        logger.info(f"Scraping competition: {overview_url}")

        # Validate URL
        if not overview_url.startswith("https://apply-for-innovation-funding.service.gov.uk"):
            logger.warning(f"URL does not match expected domain: {overview_url}")

        # Fetch HTML
        html = self._get(overview_url)
        soup = BeautifulSoup(html, "html.parser")

        # Parse components
        competition = self._parse_competition_meta(overview_url, soup, html)
        sections = self._parse_sections(competition, soup)
        resources = self._extract_supporting_resources_from_sections(competition, sections, soup)

        logger.info(
            f"Scraped: {competition.title} - "
            f"{len(sections)} sections, {len(resources)} resources"
        )

        return ScrapedCompetition(
            competition=competition,
            sections=sections,
            resources=resources,
        )

    def _get(self, url: str) -> str:
        """
        Fetch URL and return HTML.

        Args:
            url: URL to fetch

        Returns:
            HTML string

        Raises:
            requests.HTTPError: If request fails
        """
        try:
            # Temporarily disable SSL verification for UK gov sites (SSL cert issue)
            # TODO: Fix SSL certificate chain for apply-for-innovation-funding.service.gov.uk
            resp = self.session.get(url, timeout=15, verify=False)
            resp.raise_for_status()
            return resp.text
        except requests.Timeout:
            logger.error(f"Timeout fetching {url}")
            raise
        except requests.HTTPError as e:
            logger.error(f"HTTP error fetching {url}: {e}")
            raise

    def _parse_competition_meta(
        self,
        url: str,
        soup: BeautifulSoup,
        html: str
    ) -> Competition:
        """
        Extract competition metadata from page.

        This includes:
        - Title
        - IDs (internal and external)
        - Dates (opens/closes)
        - Funding details
        - Project size
        - Funding rules (percentages by company size)
        - Description

        Args:
            url: Page URL
            soup: Parsed HTML
            html: Raw HTML

        Returns:
            Competition object
        """
        logger.debug("Parsing competition metadata")

        # TITLE
        title = self._extract_title(soup)

        # IDs
        external_id, internal_id = self._extract_ids(url)

        # DATES
        opens_at, closes_at = self._extract_dates(soup)

        # FUNDING INFO
        total_fund = self._extract_total_fund(soup)
        project_size = self._extract_project_size(soup)
        funding_rules = self._extract_funding_rules(soup)

        # DESCRIPTION
        description = self._extract_description(soup)

        return Competition(
            id=internal_id,
            external_id=external_id,
            title=title,
            base_url=url,
            description=description,
            opens_at=opens_at,
            closes_at=closes_at,
            total_fund=total_fund,
            project_size=project_size,
            funding_rules=funding_rules,
            raw_html=html,
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract competition title from h1 tag."""
        h1 = soup.find("h1")
        if h1:
            return clean_text(h1.get_text())

        logger.warning("No h1 found, using fallback title")
        return "Unknown Innovate UK competition"

    def _extract_ids(self, url: str) -> Tuple[str, str]:
        """
        Extract external_id and internal_id from URL.

        External ID is the numeric competition ID from the URL path.
        Internal ID is either the external ID or a hash-based ID.

        Args:
            url: Competition URL

        Returns:
            Tuple of (external_id, internal_id)
        """
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p.strip()]

        external_id = None

        # Look for /competition/{id}/ pattern
        for i, part in enumerate(parts):
            if part == "competition" and i + 1 < len(parts):
                next_part = parts[i + 1]
                if next_part.isdigit():
                    external_id = next_part
                    break

        # Fallback: use last path segment
        if not external_id and parts:
            external_id = parts[-1]

        # Internal ID: prefer numeric ID, otherwise hash URL
        if external_id and external_id.isdigit():
            internal_id = external_id
        else:
            internal_id = stable_id_from_url(url, prefix="iuk_")

        logger.debug(f"IDs: external={external_id}, internal={internal_id}")
        return external_id or "unknown", internal_id

    def _extract_dates(self, soup: BeautifulSoup) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Extract opening and closing dates.

        Looks for list items containing "competition opens" and "competition closes".

        Args:
            soup: Parsed HTML

        Returns:
            Tuple of (opens_at, closes_at)
        """
        opens_at = None
        closes_at = None

        # Search in list items (common pattern)
        for li in soup.find_all("li"):
            text = li.get_text(" ", strip=True)
            text_lower = text.lower()

            if "competition opens" in text_lower and ":" in text:
                date_str = text.split(":", 1)[1].strip()
                opens_at = parse_date_maybe(date_str)
                logger.debug(f"Found opens date: {opens_at}")

            elif "competition closes" in text_lower and ":" in text:
                date_str = text.split(":", 1)[1].strip()
                closes_at = parse_date_maybe(date_str)
                logger.debug(f"Found closes date: {closes_at}")

        return opens_at, closes_at

    def _extract_total_fund(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract total funding amount.

        Looks for patterns like "up to £5 million".

        Args:
            soup: Parsed HTML

        Returns:
            Funding string or None
        """
        text_all = soup.get_text(" ", strip=True)
        return extract_money_amount(text_all)

    def _extract_project_size(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract project size information.

        Looks for "Project size" label followed by amount range.

        Args:
            soup: Parsed HTML

        Returns:
            Project size string or None
        """
        project_size = None

        # Search for <strong> or <b> tags containing "project size"
        for strong in soup.find_all(["strong", "b", "dt"]):
            text = strong.get_text(" ", strip=True).lower()

            if "project size" in text:
                # Get parent container
                container = strong.parent
                if not container:
                    continue

                # Try getting text from next sibling (dd tag pattern)
                if strong.name == "dt":
                    dd = strong.find_next_sibling("dd")
                    if dd:
                        project_size = clean_text(dd.get_text())
                        break

                # Try getting text from container
                full_text = container.get_text(" ", strip=True)
                if ":" in full_text:
                    project_size = full_text.split(":", 1)[1].strip()
                    break

                # Try getting text from next paragraph
                next_p = container.find_next("p")
                if next_p:
                    project_size = clean_text(next_p.get_text())
                    break

        logger.debug(f"Project size: {project_size}")
        return project_size

    def _extract_funding_rules(self, soup: BeautifulSoup) -> dict:
        """
        Extract funding percentage rules by company size.

        Looks for patterns like:
        - "up to 60% ... micro, small or medium"
        - "up to 50% ... large organisation"

        Args:
            soup: Parsed HTML

        Returns:
            Dict with keys like "micro_sme_max_pct", "large_max_pct"
        """
        funding_rules = {}
        text_all = soup.get_text(" ", strip=True)

        # Pattern: "up to 60% of eligible project costs ... micro, small or medium"
        if re.search(r"up to 60%.*micro.*small.*medium", text_all, re.IGNORECASE):
            funding_rules["micro_sme_max_pct"] = 0.60
            logger.debug("Found SME funding rule: 60%")

        # Pattern: "up to 50% ... large organisation"
        if re.search(r"up to 50%.*large\s+organisation", text_all, re.IGNORECASE):
            funding_rules["large_max_pct"] = 0.50
            logger.debug("Found large org funding rule: 50%")

        # Pattern: "up to 70% ... research organisation"
        if re.search(r"up to 70%.*research\s+organisation", text_all, re.IGNORECASE):
            funding_rules["research_max_pct"] = 0.70
            logger.debug("Found research org funding rule: 70%")

        return funding_rules

    def _extract_description(self, soup: BeautifulSoup) -> str:
        """
        Extract competition description.

        Looks for heading containing "description" and collects paragraphs
        until next major heading.

        Args:
            soup: Parsed HTML

        Returns:
            Description text
        """
        # Find "Description" heading
        header = None
        for h in soup.find_all(["h2", "h3"]):
            if "description" in h.get_text(" ", strip=True).lower():
                header = h
                break

        if not header:
            logger.warning("No description section found")
            return ""

        # Collect content until next heading
        parts = []
        for sib in header.find_next_siblings():
            # Stop at next major section
            if sib.name in ("h2", "h3"):
                break

            if sib.name in ("p", "ul", "ol", "div"):
                text = clean_text(sib.get_text(" ", strip=True))
                if text:
                    parts.append(text)

        description = "\n\n".join(parts)
        logger.debug(f"Description length: {len(description)} chars")
        return description

    def _parse_sections(
        self,
        comp: Competition,
        soup: BeautifulSoup
    ) -> List[CompetitionSection]:
        """
        Parse page into logical sections using the Competition sections nav.

        Strategy:
        1. Find "Competition sections" heading and its navigation list
        2. Extract section names and fragment IDs from nav links
        3. For each section, find content and collect until next section

        Args:
            comp: Competition object
            soup: Parsed HTML

        Returns:
            List of CompetitionSection objects
        """
        logger.debug("Parsing sections from navigation")
        sections: List[CompetitionSection] = []

        # STEP 1: Find the "Competition sections" navigation
        nav_sections = self._find_competition_sections_nav(soup)

        if not nav_sections:
            logger.warning("Could not find 'Competition sections' nav, using fallback")
            return self._parse_sections_fallback(comp, soup)

        logger.debug(f"Found {len(nav_sections)} sections in nav")

        # STEP 2: For each nav section, find and collect content
        all_fragments = [frag for _, frag, _ in nav_sections]
        all_link_texts = [text for _, _, text in nav_sections]

        for section_name, fragment, link_text in nav_sections:
            logger.debug(f"Processing section: {section_name} (#{fragment})")

            # Find the starting element for this section
            target = self._find_section_start(soup, fragment, link_text)

            if not target:
                logger.warning(f"Could not find content for section: {section_name}")
                continue

            # Collect content until next section
            html_content, text_content = self._collect_section_content_until_next(
                target, all_fragments, all_link_texts
            )

            if not html_content.strip() and not text_content.strip():
                logger.debug(f"Empty section: {section_name}")
                continue

            section_url = f"{comp.base_url}#{fragment}"

            sections.append(
                CompetitionSection(
                    competition_id=comp.id,
                    name=section_name,
                    url=section_url,
                    html=html_content,
                    text=text_content,
                )
            )
            logger.debug(f"Parsed section: {section_name} ({len(text_content)} chars)")

        return sections

    def _find_section_header(
        self,
        headers: List[Tuple[Tag, str, str]],
        anchor: str
    ) -> Optional[Tag]:
        """
        Find header matching section anchor.

        First tries exact ID match, then text match.

        Args:
            headers: List of (tag, id, text) tuples
            anchor: Section anchor to find

        Returns:
            Matching header tag or None
        """
        # Try exact ID match
        for h, sec_id, sec_text in headers:
            if sec_id == anchor:
                return h

        # Try text match (anchor with dashes -> spaces)
        anchor_text = anchor.replace("-", " ")
        for h, sec_id, sec_text in headers:
            if anchor_text in sec_text:
                return h

        return None

    def _collect_section_content(self, header: Tag) -> Tuple[str, str]:
        """
        Collect HTML and text content from header until next heading.

        Args:
            header: Starting header tag

        Returns:
            Tuple of (html_content, text_content)
        """
        html_parts = []
        text_parts = []

        for sib in header.find_next_siblings():
            # Stop at next major heading
            if sib.name in ("h2", "h3"):
                break

            if sib.name in ("p", "ul", "ol", "div", "table", "dl"):
                html_parts.append(str(sib))
                text = clean_text(sib.get_text(" ", strip=True))
                if text:
                    text_parts.append(text)

        html_content = "".join(html_parts)
        text_content = "\n\n".join(text_parts)

        return html_content, text_content

    def _find_competition_sections_nav(self, soup: BeautifulSoup) -> List[Tuple[str, str, str]]:
        """
        Find the 'Competition sections' navigation and extract section info.

        Returns:
            List of (normalized_name, fragment, link_text) tuples
        """
        # Mapping for normalizing section names
        NAME_MAP = {
            "summary": "summary",
            "eligibility": "eligibility",
            "scope": "scope",
            "dates": "dates",
            "how to apply": "how-to-apply",
            "supporting information": "supporting-information",
        }

        # Find heading containing "Competition sections"
        nav_heading = None
        for h in soup.find_all(["h2", "h3", "h4"]):
            h_text = h.get_text(strip=True).lower()
            if "competition sections" in h_text or "competition section" in h_text:
                nav_heading = h
                logger.debug(f"Found nav heading: {h.get_text(strip=True)}")
                break

        if not nav_heading:
            # Try finding nav with specific class
            nav_element = soup.find("nav", class_=lambda x: x and "competition" in str(x).lower())
            if nav_element:
                nav_heading = nav_element.find(["h2", "h3", "h4"])

            if not nav_heading:
                logger.warning("Could not find 'Competition sections' heading")
                return []

        # Find the first <ul> after this heading
        nav_list = None
        for sibling in nav_heading.find_next_siblings():
            if sibling.name == "ul":
                nav_list = sibling
                break
            # Also check if ul is nested inside a div
            if sibling.name in ["div", "nav"]:
                nav_list = sibling.find("ul")
                if nav_list:
                    break

        if not nav_list:
            logger.warning("Could not find nav list after 'Competition sections' heading")
            return []

        # Extract sections from nav links
        nav_sections = []
        for a in nav_list.find_all("a", href=True):
            href = a.get("href", "").strip()
            link_text = a.get_text(strip=True)

            if not href.startswith("#"):
                continue

            fragment = href[1:].strip().lower()
            link_text_lower = link_text.lower()

            # Normalize the name
            normalized_name = NAME_MAP.get(link_text_lower, fragment or link_text_lower.replace(" ", "-"))

            nav_sections.append((normalized_name, fragment, link_text))
            logger.debug(f"Nav section: {normalized_name} -> #{fragment}")

        return nav_sections

    def _find_section_start(self, soup: BeautifulSoup, fragment: str, link_text: str) -> Optional[Tag]:
        """
        Find the starting element for a section.

        Tries:
        1. Element with id=fragment
        2. Heading containing link_text

        Args:
            soup: Parsed HTML
            fragment: Fragment ID (e.g., "summary")
            link_text: Section link text (e.g., "Summary")

        Returns:
            Starting element or None
        """
        # Try finding by ID first
        target = soup.find(id=fragment)
        if target:
            logger.debug(f"Found section by ID: #{fragment}")
            return target

        # Try finding heading with matching text
        link_text_lower = link_text.lower()
        for h in soup.find_all(["h2", "h3"]):
            h_text = h.get_text(strip=True).lower()
            if link_text_lower in h_text or h_text in link_text_lower:
                logger.debug(f"Found section by heading text: {h_text}")
                return h

        logger.warning(f"Could not find section start for: {link_text} (#{fragment})")
        return None

    def _collect_section_content_until_next(
        self,
        start_element,
        all_fragments: List[str],
        all_link_texts: List[str]
    ) -> Tuple[str, str]:
        """
        Collect content from start_element until the next section.

        Stops when encountering:
        - An element with id in all_fragments
        - A heading matching one of all_link_texts

        Args:
            start_element: Starting element
            all_fragments: List of all section fragment IDs
            all_link_texts: List of all section link texts

        Returns:
            Tuple of (html_content, text_content)
        """
        html_parts = []
        text_parts = []

        # If start_element is the section container itself, get children
        if start_element.name in ["section", "div", "article"]:
            elements_to_process = start_element.find_all(["p", "ul", "ol", "div", "table", "dl", "h2", "h3", "h4"], recursive=False)
        else:
            # Start from next sibling
            elements_to_process = start_element.find_next_siblings()

        for elem in elements_to_process:
            # Stop if we hit another section
            elem_id = (elem.get("id") or "").strip().lower()
            if elem_id in all_fragments:
                logger.debug(f"Stopping at section boundary: #{elem_id}")
                break

            # Stop if we hit a heading that matches another section
            if elem.name in ["h2", "h3"]:
                elem_text = elem.get_text(strip=True).lower()
                if any(link_text.lower() in elem_text for link_text in all_link_texts if link_text.lower() != elem_text):
                    logger.debug(f"Stopping at heading: {elem_text}")
                    break

            # Collect content
            if elem.name in ["p", "ul", "ol", "div", "table", "dl", "details"]:
                html_parts.append(str(elem))
                text = clean_text(elem.get_text(" ", strip=True))
                if text:
                    text_parts.append(text)

        html_content = "".join(html_parts)
        text_content = "\n\n".join(text_parts)

        return html_content, text_content

    def _parse_sections_fallback(self, comp: Competition, soup: BeautifulSoup) -> List[CompetitionSection]:
        """
        Fallback section parsing when nav is not found.

        Uses the original SECTION_ANCHORS approach.
        """
        logger.debug("Using fallback section parsing")
        sections: List[CompetitionSection] = []

        # Find all h2/h3 headers
        headers = []
        for h in soup.find_all(["h2", "h3"]):
            sec_id = (h.get("id") or "").strip().lower()
            sec_text = h.get_text(" ", strip=True).lower()
            headers.append((h, sec_id, sec_text))

        # For each known section anchor
        for name, anchor in self.SECTION_ANCHORS.items():
            target_header = self._find_section_header(headers, anchor)

            if not target_header:
                continue

            # Collect content until next heading
            html_content, text_content = self._collect_section_content(target_header)

            if not html_content.strip() and not text_content.strip():
                continue

            section_url = f"{comp.base_url}#{anchor}"

            sections.append(
                CompetitionSection(
                    competition_id=comp.id,
                    name=name,
                    url=section_url,
                    html=html_content,
                    text=text_content,
                )
            )

        return sections

    def _extract_supporting_resources_from_sections(
        self,
        comp: Competition,
        sections: List[CompetitionSection],
        soup: BeautifulSoup
    ) -> List[SupportingResource]:
        """
        Extract supporting resources from the supporting-information section.

        Captures ALL meaningful HTTP(S) links, not just PDFs/videos.

        Args:
            comp: Competition object
            sections: List of parsed sections
            soup: Full page soup (fallback)

        Returns:
            List of SupportingResource objects
        """
        logger.debug("Extracting supporting resources from sections")

        # Find the supporting-information section
        supporting_section = next(
            (s for s in sections if s.name == "supporting-information"),
            None
        )

        if not supporting_section or not supporting_section.html:
            logger.warning("No supporting-information section found, using fallback")
            return self._extract_supporting_resources_fallback(comp, soup)

        logger.debug("Found supporting-information section")

        # Parse resources from this section's HTML
        section_soup = BeautifulSoup(supporting_section.html, "html.parser")

        resources: List[SupportingResource] = []
        seen_urls: set = set()

        # Extract all links from the section
        for a in section_soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            title = a.get_text(" ", strip=True) or None

            # Build resource (with filtering logic inside)
            res = self._build_supporting_resource_from_link(
                comp=comp,
                href=href,
                link_text=title,
                seen=seen_urls,
            )

            if res is not None:
                resources.append(res)

        logger.info(f"Extracted {len(resources)} resources from supporting-information section")
        return resources

    def _build_supporting_resource_from_link(
        self,
        comp: Competition,
        href: str,
        link_text: Optional[str],
        seen: set,
    ) -> Optional[SupportingResource]:
        """
        Build a SupportingResource from a link, applying minimal filtering.

        Only skips:
        - Empty/junk links (mailto:, tel:, javascript:, #fragments)
        - Duplicate URLs

        Args:
            comp: Competition object
            href: Link href attribute
            link_text: Link text content
            seen: Set of already-seen URLs (updated in place)

        Returns:
            SupportingResource or None if link should be skipped
        """
        # Skip empty
        if not href:
            return None

        href = href.strip()

        # Skip non-HTTP links
        if href.startswith("#"):
            return None
        if href.startswith(("mailto:", "tel:", "javascript:")):
            return None

        # Make absolute URL
        full_url = urljoin(comp.base_url, href)

        # Skip duplicates
        if full_url in seen:
            return None
        seen.add(full_url)

        # Classify (but don't filter by classification)
        scope = self._classify_scope(full_url, comp)
        r_type = self._infer_type(full_url, link_text=link_text)
        res_id = stable_id_from_url(full_url, prefix="res_")

        logger.debug(f"Resource: {link_text} → {full_url} ({scope}/{r_type})")

        return SupportingResource(
            id=res_id,
            url=full_url,
            title=link_text,
            competition_id=comp.id if scope == ResourceScope.COMPETITION else None,
            scope=scope,
            type=r_type,
            content_hash=None,
        )

    def _extract_resources_from_element(
        self,
        comp: Competition,
        element: BeautifulSoup,
    ) -> List[SupportingResource]:
        """
        Extract resources from any element.

        SIMPLIFIED: No longer filters by type/domain.
        """
        resources: List[SupportingResource] = []
        seen_urls: set = set()

        for a in element.find_all("a", href=True):
            href = a.get("href", "")
            title = a.get_text(" ", strip=True) or None

            res = self._build_supporting_resource_from_link(
                comp=comp,
                href=href,
                link_text=title,
                seen=seen_urls,
            )

            if res is not None:
                resources.append(res)

        return resources

    def _extract_supporting_resources_fallback(
        self,
        comp: Competition,
        soup: BeautifulSoup
    ) -> List[SupportingResource]:
        """
        Fallback: scan entire page for supporting resources.

        This is the original implementation.
        """
        logger.debug("Using fallback resource extraction")

        # Find "Supporting information" heading
        header = None
        for h in soup.find_all(["h2", "h3"]):
            if "supporting information" in h.get_text(" ", strip=True).lower():
                header = h
                break

        if not header:
            logger.warning("No supporting information section found")
            return []

        # Collect content after heading
        content_nodes = []
        for sib in header.find_next_siblings():
            if sib.name in ("h2", "h3"):
                break
            content_nodes.append(sib)

        # Create a temporary soup from these nodes
        temp_html = "".join(str(node) for node in content_nodes)
        temp_soup = BeautifulSoup(temp_html, "html.parser")

        return self._extract_resources_from_element(comp, temp_soup)

    def _classify_scope(self, url: str, comp: Competition) -> ResourceScope:
        """
        Classify resource as GLOBAL or COMPETITION-specific.

        Heuristics:
        - URL contains competition's external ID -> COMPETITION
        - URL on apply-for-innovation-funding + /competition/ path -> COMPETITION
        - Otherwise -> GLOBAL (generic guidance)

        Args:
            url: Resource URL
            comp: Competition object

        Returns:
            ResourceScope enum
        """
        parsed = urlparse(url)
        path = parsed.path.lower()

        # Check if URL contains competition ID
        if comp.external_id and comp.external_id in path:
            return ResourceScope.COMPETITION

        # Check if on competition service and has /competition/ in path
        if (
            "apply-for-innovation-funding.service.gov.uk" in parsed.netloc
            and "/competition/" in path
        ):
            return ResourceScope.COMPETITION

        # Default to GLOBAL
        return ResourceScope.GLOBAL

    def _infer_type(self, url: str, link_text: Optional[str] = None) -> ResourceType:
        """
        Infer resource type from URL and link text.

        Enhanced to handle:
        - Direct PDF URLs (.pdf extension)
        - Download endpoints (/competition/.../download/...)
        - Link text containing PDF indicators
        - Video hosting platforms

        Args:
            url: Resource URL
            link_text: Text content of the link (optional but recommended)

        Returns:
            ResourceType enum
        """
        lower_url = url.lower()
        lower_text = (link_text or "").lower()

        # 1. Direct PDF extension in URL
        if lower_url.endswith(".pdf"):
            return ResourceType.PDF

        # 2. Innovate UK download endpoints (usually PDFs)
        # Pattern: /competition/{id}/download/{file_id}
        if "/download/" in lower_url and "competition" in lower_url:
            logger.debug(f"Detected download endpoint as PDF: {url}")
            return ResourceType.PDF

        # 3. Link text strongly suggests PDF
        # Examples: "Briefing Slides.pdf", "guidance.pdf (opens in new window)"
        if ".pdf" in lower_text:
            logger.debug(f"Detected PDF from link text: {link_text}")
            return ResourceType.PDF

        # 4. Video platforms
        video_domains = ["youtube.com", "youtu.be", "vimeo.com", "webex.com", "zoom.us"]
        if any(domain in lower_url for domain in video_domains):
            return ResourceType.VIDEO

        # 5. Other document types (optional, can expand)
        if any(lower_url.endswith(ext) for ext in [".doc", ".docx", ".ppt", ".pptx"]):
            return ResourceType.PDF  # Treat office docs as PDFs for now

        # 6. Default to webpage
        if lower_url.startswith("http"):
            return ResourceType.WEBPAGE

        return ResourceType.OTHER
