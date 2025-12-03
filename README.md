# Innovate UK Grant Scraper

A production-ready web scraper for Innovate UK funding competitions. Part of the ASK AILSA grant discovery platform.

## Features

- **Scrapes Innovate UK competitions** - Extracts metadata, funding details, and supporting resources
- **Competition type detection** - Automatically classifies grants, loans, and prizes
- **Per-project funding extraction** - Extracts individual project funding ranges
- **Expected winners calculation** - Estimates number of winners based on funding
- **Retry logic with exponential backoff** - Handles transient failures gracefully
- **Rate limiting** - Respects server limits with configurable delays
- **Monitoring and alerting** - Tracks failures and sends alerts
- **Dead letter queue** - Persistent failure tracking for manual review

## Quick Start

```bash
# Install dependencies
pip3 install -r requirements.txt

# Setup MongoDB (creates collections and indexes)
mongosh < mongo_setup.js

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Test connections
python3 test_connections.py

# Run scraper
python3 ingest_innovate_uk.py
```

## Architecture

```
Competition URL → Scraper → Normalizer → MongoDB + Pinecone
                    ↓
               Monitoring
                    ↓
              Failure Queue
```

## Document Schema

Grant documents in MongoDB (`ailsa_grants.grants`):

| Field | Type | Description |
|-------|------|-------------|
| `grant_id` | String | Unique identifier |
| `competition_type` | String | grant, loan, or prize |
| `project_funding_min` | Number | Minimum per-project funding (GBP) |
| `project_funding_max` | Number | Maximum per-project funding (GBP) |
| `expected_winners` | Number | Estimated number of winners |
| `total_fund_gbp` | Number | Total funding pot (GBP) |
| `sections` | Array | Embedded page sections |
| `resources` | Array | Embedded supporting resources |

## Configuration

All configuration is done via environment variables in `.env`:

```bash
OPENAI_API_KEY=your_key       # For embeddings
PINECONE_API_KEY=your_key     # Vector database
PINECONE_INDEX_NAME=ailsa-grants
MONGO_URI=mongodb://localhost:27017  # MongoDB connection
```

Constants can be adjusted in `src/core/constants.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `REQUEST_TIMEOUT` | 15 | HTTP request timeout (seconds) |
| `RATE_LIMIT_DELAY_MIN` | 1.0 | Minimum delay between requests |
| `RATE_LIMIT_DELAY_MAX` | 2.0 | Maximum delay between requests |
| `MAX_RETRIES` | 3 | Number of retry attempts |
| `BACKOFF_FACTOR` | 2 | Exponential backoff multiplier |
| `TYPICAL_PROJECT_PERCENT` | 0.70 | For expected winners calculation |

## Monitoring

### Health Check

```bash
# Run health check
./check_scraper_health.sh

# With email alerts
./check_scraper_health.sh --email admin@example.com
```

### Log Files

- `logs/scraper_*.log` - Detailed scrape logs
- `logs/scraper_stats_*.json` - Run statistics
- `logs/failed_competitions_*.json` - Failure details

### Success Criteria

The scraper alerts if:
- Success rate falls below 95%
- More than 3 competitions have persistent failures

## Competition Types

| Type | Detection | Examples |
|------|-----------|----------|
| `grant` | Default | R&D grants, SBRI |
| `loan` | "loan" in title/description | Innovation Loan |
| `prize` | "prize" in title/description | Challenge prizes |

## Expected Winners Calculation

Formula: `expected_winners = total_fund / (project_max * 0.7)`

The 70% factor accounts for projects typically not reaching maximum funding.

## Testing

```bash
# Run unit tests
pytest tests/ -v

# Run specific test class
pytest tests/test_innovate_uk_scraper.py::TestCompetitionTypeDetection -v
```

## Cron Scheduling

Recommended: Twice weekly (Tuesday and Friday at 2 AM)

```bash
# Add to crontab
0 2 * * 2,5 /path/to/run_scraper.sh >> /path/to/logs/cron.log 2>&1
30 2 * * 2,5 /path/to/check_scraper_health.sh --email admin@example.com >> /path/to/logs/health.log 2>&1
```

## File Structure

```
IUK scraper/
├── ingest_innovate_uk.py     # Main ingestion pipeline
├── innovateuk_competition.py # Competition scraper
├── check_scraper_health.sh   # Health check script
├── run_scraper.sh            # Cron wrapper
├── mongo_setup.js            # MongoDB setup script
├── requirements.txt          # Python dependencies
├── src/
│   ├── core/
│   │   ├── constants.py      # Configuration constants
│   │   ├── models.py         # Scraping models
│   │   └── domain_models.py  # Domain models
│   ├── ingest/               # Scrapers
│   ├── normalize/            # Data normalization
│   ├── monitoring/           # Failure tracking
│   ├── storage/              # Storage utilities
│   └── index/                # Pinecone
├── tests/                    # Unit tests
└── logs/                     # Log files
```

## API

### InnovateUKCompetitionScraper

```python
from innovateuk_competition import InnovateUKCompetitionScraper

scraper = InnovateUKCompetitionScraper()
result = scraper.scrape_competition(url)

# result.competition - Competition metadata
# result.sections - Page sections (eligibility, scope, etc.)
# result.resources - Supporting documents
```

### ScraperMonitor

```python
from src.monitoring.scraper_stats import ScraperMonitor

monitor = ScraperMonitor()
monitor.log_attempt(competition_id="2341", url="...", success=True)
stats = monitor.finalize()
monitor.export_failures("failures.json")
```

## Troubleshooting

### SSL Errors

The scraper uses `certifi` for SSL verification. If errors persist:

```bash
pip install --upgrade certifi
```

### Rate Limiting

If you see 429 errors, increase delays in `src/core/constants.py`:

```python
RATE_LIMIT_DELAY_MIN = 2.0
RATE_LIMIT_DELAY_MAX = 4.0
```

### MongoDB Setup

Run the setup script to create indexes:

```bash
mongosh < mongo_setup.js
```

Verify setup:

```bash
mongosh ailsa_grants --eval "db.grants.getIndexes()"
```

## Performance

- **36 competitions**: ~5-10 minutes
- **Rate limiting**: 1-2 second delay per request
- **Retries**: Up to 3 with exponential backoff
- **OpenAI cost**: ~$0.10 per run

## License

Proprietary - ASK AILSA

## Support

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment instructions.
