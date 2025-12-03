#!/usr/bin/env python3
"""
Update innovate_uk_urls.txt with new competitions from the search page.
Run this periodically to discover new competitions automatically.
"""

import requests
from bs4 import BeautifulSoup
from pathlib import Path
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SEARCH_URL = "https://apply-for-innovation-funding.service.gov.uk/competition/search"
URLS_FILE = Path("innovate_uk_urls.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}


def fetch_competition_urls():
    """Fetch competition URLs from Innovate UK search page"""
    print(f"🔍 Fetching competitions from: {SEARCH_URL}")

    try:
        resp = requests.get(SEARCH_URL, headers=HEADERS, verify=False, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')

        # Find all competition links
        links = soup.find_all('a', href=True)
        comp_urls = set()

        for a in links:
            href = a['href']
            # Match pattern: /competition/XXXX/overview/UUID
            if '/competition/' in href and '/overview/' in href:
                # Make absolute URL
                if href.startswith('/'):
                    full_url = f"https://apply-for-innovation-funding.service.gov.uk{href}"
                else:
                    full_url = href
                comp_urls.add(full_url)

        print(f"✅ Found {len(comp_urls)} competition URLs")
        return sorted(comp_urls)

    except Exception as e:
        print(f"❌ Error fetching URLs: {e}")
        return []


def load_existing_urls():
    """Load existing URLs from file"""
    if not URLS_FILE.exists():
        return set()

    with URLS_FILE.open() as f:
        urls = {
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        }

    return urls


def save_urls(urls):
    """Save URLs to file"""
    with URLS_FILE.open('w') as f:
        f.write("# Innovate UK Grant URLs\n")
        f.write("# Auto-updated by update_urls.py\n")
        f.write("# Lines starting with # are ignored\n\n")
        f.write("# Add more URLs below (one per line)\n")

        for url in sorted(urls):
            f.write(f"{url}\n")


def main():
    print("=" * 70)
    print("INNOVATE UK - URL UPDATER")
    print("=" * 70)

    # Fetch new URLs
    new_urls = set(fetch_competition_urls())

    if not new_urls:
        print("⚠️  No URLs found - check connection or search page structure")
        return

    # Load existing URLs
    existing_urls = load_existing_urls()
    print(f"📁 Existing URLs in file: {len(existing_urls)}")

    # Find additions
    added_urls = new_urls - existing_urls
    removed_urls = existing_urls - new_urls

    print(f"\n📊 Changes:")
    print(f"   ➕ New: {len(added_urls)}")
    print(f"   ➖ Removed: {len(removed_urls)}")
    print(f"   ✓ Total: {len(new_urls)}")

    if added_urls:
        print(f"\n➕ New competitions:")
        for url in sorted(added_urls)[:5]:
            comp_id = url.split('/')[-3]
            print(f"   - Competition {comp_id}")
        if len(added_urls) > 5:
            print(f"   ... and {len(added_urls) - 5} more")

    if removed_urls:
        print(f"\n➖ Removed competitions:")
        for url in sorted(removed_urls)[:5]:
            comp_id = url.split('/')[-3]
            print(f"   - Competition {comp_id}")
        if len(removed_urls) > 5:
            print(f"   ... and {len(removed_urls) - 5} more")

    # Merge and save
    all_urls = new_urls | existing_urls  # Keep all (new + existing)
    save_urls(all_urls)

    print(f"\n✅ Updated {URLS_FILE}")
    print(f"   Total URLs: {len(all_urls)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
