#!/usr/bin/env python3
"""
Auto-discover Innovate UK competition URLs from the search page.

This script:
1. Scrapes the competition search page
2. Finds all competition URLs (via pagination)
3. Compares with existing URLs in innovate_uk_urls.txt
4. Optionally adds new URLs to the file

Usage:
    # Just show what's new (dry run)
    python scripts/discover_competitions.py

    # Add new URLs to the file
    python scripts/discover_competitions.py --update

    # Show all discovered URLs
    python scripts/discover_competitions.py --verbose
"""

import argparse
import sys
import time
import random
from pathlib import Path
from datetime import datetime
from typing import Set, List
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import certifi


# Configuration
SEARCH_URL = "https://apply-for-innovation-funding.service.gov.uk/competition/search"
BASE_URL = "https://apply-for-innovation-funding.service.gov.uk"
URL_FILE = Path(__file__).parent.parent / "data" / "urls" / "innovate_uk_urls.txt"

# Rate limiting
MIN_DELAY = 1.0
MAX_DELAY = 2.0

# HTTP settings
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
BACKOFF_FACTOR = 2
RETRY_STATUS_CODES = [429, 500, 502, 503, 504]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def create_session() -> requests.Session:
    """Create a requests session with retry logic."""
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=RETRY_STATUS_CODES,
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(DEFAULT_HEADERS)
    return session


def discover_competitions(session: requests.Session, verbose: bool = False) -> Set[str]:
    """
    Discover all competition URLs from the search page.

    Args:
        session: Configured requests session
        verbose: Print progress information

    Returns:
        Set of full competition URLs
    """
    all_urls: Set[str] = set()
    page = 0
    max_pages = 50  # Safety limit

    while page < max_pages:
        if verbose:
            print(f"  Fetching page {page}...", end=" ", flush=True)

        # Add rate limiting
        if page > 0:
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            time.sleep(delay)

        try:
            resp = session.get(
                f"{SEARCH_URL}?page={page}",
                timeout=REQUEST_TIMEOUT,
                verify=certifi.where(),
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"\n  Error fetching page {page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        # Find all competition overview links
        page_urls: Set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/competition/" in href and "/overview/" in href:
                # Make absolute URL
                full_url = urljoin(BASE_URL, href)
                page_urls.add(full_url)

        # Track new URLs
        new_count = len(page_urls - all_urls)
        all_urls.update(page_urls)

        if verbose:
            print(f"found {len(page_urls)} links, {new_count} new")

        # Stop if no new URLs found (end of pagination)
        if new_count == 0 and page > 0:
            if verbose:
                print("  No new links found, stopping pagination.")
            break

        page += 1

    return all_urls


def load_existing_urls(filepath: Path) -> Set[str]:
    """Load existing URLs from the URL file."""
    if not filepath.exists():
        return set()

    urls: Set[str] = set()
    with filepath.open() as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.add(line)

    return urls


def save_urls(filepath: Path, urls: Set[str], new_urls: Set[str]) -> None:
    """
    Save URLs to file, appending new ones at the end.

    Args:
        filepath: Path to URL file
        urls: All existing URLs
        new_urls: New URLs to add
    """
    # Read existing content
    existing_content = ""
    if filepath.exists():
        existing_content = filepath.read_text()

    # Ensure file ends with newline
    if existing_content and not existing_content.endswith("\n"):
        existing_content += "\n"

    # Add new URLs with header comment
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_section = f"\n# Auto-discovered on {timestamp}\n"
    for url in sorted(new_urls):
        new_section += f"{url}\n"

    # Write updated file
    filepath.write_text(existing_content + new_section)


def main():
    parser = argparse.ArgumentParser(
        description="Discover new Innovate UK competition URLs"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Add new URLs to innovate_uk_urls.txt",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed progress",
    )
    parser.add_argument(
        "--url-file",
        type=Path,
        default=URL_FILE,
        help=f"Path to URL file (default: {URL_FILE})",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("INNOVATE UK COMPETITION URL DISCOVERY")
    print("=" * 60)
    print()

    # Create session
    session = create_session()

    # Discover competitions from search page
    print("🔍 Discovering competitions from search page...")
    discovered_urls = discover_competitions(session, verbose=args.verbose)
    print(f"   Found {len(discovered_urls)} competitions on search page")
    print()

    # Load existing URLs
    print(f"📁 Loading existing URLs from {args.url_file}...")
    existing_urls = load_existing_urls(args.url_file)
    print(f"   Found {len(existing_urls)} existing URLs")
    print()

    # Find new URLs
    new_urls = discovered_urls - existing_urls
    removed_urls = existing_urls - discovered_urls

    # Report findings
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  📊 Discovered: {len(discovered_urls)}")
    print(f"  📄 Existing:   {len(existing_urls)}")
    print(f"  🆕 New:        {len(new_urls)}")
    print(f"  📦 In file but not on search: {len(removed_urls)}")
    print()

    if new_urls:
        print("🆕 NEW COMPETITIONS:")
        for url in sorted(new_urls):
            # Extract competition ID for display
            comp_id = url.split("/competition/")[1].split("/")[0]
            print(f"   [{comp_id}] {url}")
        print()

    if removed_urls and args.verbose:
        print("📦 IN FILE BUT NOT ON SEARCH PAGE (may be closed):")
        for url in sorted(removed_urls)[:10]:
            comp_id = url.split("/competition/")[1].split("/")[0]
            print(f"   [{comp_id}] {url}")
        if len(removed_urls) > 10:
            print(f"   ... and {len(removed_urls) - 10} more")
        print()

    # Update file if requested
    if args.update and new_urls:
        print(f"✏️  Adding {len(new_urls)} new URLs to {args.url_file}...")
        save_urls(args.url_file, existing_urls, new_urls)
        print("   Done!")
        print()
    elif new_urls and not args.update:
        print("💡 Run with --update to add new URLs to the file")
        print()

    if not new_urls:
        print("✅ No new competitions found - URL file is up to date!")
        print()

    print("=" * 60)

    # Return exit code based on findings
    return 0 if not new_urls else 1


if __name__ == "__main__":
    sys.exit(main())
