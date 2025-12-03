"""
Constants for the Innovate UK scraper.

This module centralizes all magic numbers and configuration values
to make the codebase more maintainable and configurable.
"""

# =============================================================================
# TEXT PROCESSING
# =============================================================================

# Maximum description length before truncation for embeddings
MAX_DESCRIPTION_LENGTH = 3000

# When truncating, keep this many chars from start
DESCRIPTION_TRUNCATE_START = 2500

# When truncating, keep this many chars from end
DESCRIPTION_TRUNCATE_END = 500

# Maximum section text length for embeddings
MAX_SECTION_LENGTH = 1000

# Minimum section text length to include
MIN_SECTION_LENGTH = 100


# =============================================================================
# EMBEDDING
# =============================================================================

# OpenAI embedding model
EMBEDDING_MODEL = "text-embedding-3-small"

# Maximum tokens for embedding (model limit is 8191)
MAX_EMBEDDING_TOKENS = 8000


# =============================================================================
# SCRAPING - HTTP/Network
# =============================================================================

# Request timeout in seconds
REQUEST_TIMEOUT = 15

# User-Agent header (browser-like to avoid blocking)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# =============================================================================
# RATE LIMITING
# =============================================================================

# Minimum delay between requests (seconds)
RATE_LIMIT_DELAY_MIN = 1.0

# Maximum delay between requests (seconds) - actual delay is random in range
RATE_LIMIT_DELAY_MAX = 2.0


# =============================================================================
# RETRY CONFIGURATION
# =============================================================================

# Maximum number of retry attempts
MAX_RETRIES = 3

# Backoff factor for exponential backoff (delay = backoff_factor * (2 ** attempt))
BACKOFF_FACTOR = 2

# HTTP status codes that should trigger a retry
RETRY_STATUS_CODES = [429, 500, 502, 503, 504]


# =============================================================================
# MONITORING
# =============================================================================

# Number of failures before a competition is flagged for manual review
FAILURE_THRESHOLD = 3

# Maximum failed competitions to keep in memory
MAX_FAILED_COMPETITIONS = 1000


# =============================================================================
# DATABASE
# =============================================================================

# Pinecone index name (default)
DEFAULT_PINECONE_INDEX = "ailsa-grants"

# Source identifier for Innovate UK
SOURCE_INNOVATE_UK = "innovate_uk"


# =============================================================================
# EXPECTED WINNERS CALCULATION
# =============================================================================

# Typical project amount as percentage of max (per SME feedback)
TYPICAL_PROJECT_PERCENT = 0.70


# =============================================================================
# COMPETITION TYPES
# =============================================================================

COMPETITION_TYPE_GRANT = "grant"
COMPETITION_TYPE_LOAN = "loan"
COMPETITION_TYPE_PRIZE = "prize"


# =============================================================================
# KNOWN SECTION ANCHORS
# =============================================================================

SECTION_ANCHORS = {
    "summary": "summary",
    "eligibility": "eligibility",
    "scope": "scope",
    "dates": "dates",
    "how-to-apply": "how-to-apply",
    "supporting-information": "supporting-information",
}


# =============================================================================
# HTTP HEADERS
# =============================================================================

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
