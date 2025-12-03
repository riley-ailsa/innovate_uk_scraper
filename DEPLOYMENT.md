# Innovate UK Scraper - Deployment Guide

## 🚀 Quick Setup

### 1. Install Dependencies
```bash
pip3 install -r requirements.txt
```

### 2. Configure Environment
Create `.env` file with:
```bash
OPENAI_API_KEY=your_key_here
PINECONE_API_KEY=your_key_here
PINECONE_INDEX_NAME=ailsa-grants
MONGO_URI=mongodb://localhost:27017
```

### 3. Setup MongoDB
```bash
# Run the setup script to create collections and indexes
mongosh < mongo_setup.js

# Or connect to a specific URI
mongosh "mongodb://your-host:27017" < mongo_setup.js
```

### 4. Test Connections
```bash
python3 test_connections.py
```

Should show:
- ✅ Pinecone connected
- ✅ MongoDB connected
- ✅ OpenAI connected

---

## 📅 Cron Scheduling

### Recommended Schedule
```bash
# Twice weekly: Tuesday 2 AM, Friday 2 AM (recommended)
0 2 * * 2,5 /path/to/IUK\ scraper/run_scraper.sh >> /path/to/IUK\ scraper/logs/cron.log 2>&1

# Run health check 30 minutes after scraper
30 2 * * 2,5 /path/to/IUK\ scraper/check_scraper_health.sh --email admin@ailsa.com >> /path/to/IUK\ scraper/logs/health.log 2>&1
```

### Option A: Interactive Setup (Recommended)
```bash
./setup_cron.sh
```

Choose from:
1. Daily at 2:00 AM
2. Every 6 hours
3. Every 12 hours
4. Weekly (Sundays at 2:00 AM)
5. Custom schedule

### Option B: Manual Setup
```bash
crontab -e
```

Add one of these:
```bash
# Daily at 2 AM
0 2 * * * /path/to/IUK\ scraper/run_scraper.sh >> /path/to/IUK\ scraper/logs/cron.log 2>&1

# Every 6 hours
0 */6 * * * /path/to/IUK\ scraper/run_scraper.sh >> /path/to/IUK\ scraper/logs/cron.log 2>&1

# Weekly on Sundays at 2 AM
0 2 * * 0 /path/to/IUK\ scraper/run_scraper.sh >> /path/to/IUK\ scraper/logs/cron.log 2>&1
```

---

## 🐳 Docker Deployment

### Build Image
```bash
docker build -t innovate-uk-scraper .
```

### Run Container
```bash
docker run -d \
  --name iuk-scraper \
  --env-file .env \
  -v $(pwd)/logs:/app/logs \
  innovate-uk-scraper
```

### With Docker Compose
```bash
docker-compose up -d
```

---

## 📊 Monitoring

### Health Check Script
Run the automated health check:
```bash
# Basic health check
./check_scraper_health.sh

# With email alerts
./check_scraper_health.sh --email admin@example.com
```

The health check script:
- Analyzes the latest log and stats files
- Counts errors and SSL issues
- Checks success rate (alerts if < 95%)
- Identifies persistent failures
- Sends email alerts if problems detected

### View Logs
```bash
# Latest log
ls -t logs/scraper_*.log | head -1 | xargs tail -f

# All logs from today
cat logs/scraper_$(date +%Y%m%d)*.log

# Follow cron log
tail -f logs/cron.log

# View scraper statistics
cat logs/scraper_stats_*.json | jq .
```

### Failure Analysis
```bash
# View failed competitions
cat logs/failed_competitions_*.json | jq '.persistent_failures'

# Count errors by type
cat logs/failed_competitions_*.json | jq '.summary.error_summary'
```

### Check Cron Status
```bash
# List installed cron jobs
crontab -l

# Check if scraper is running
ps aux | grep ingest_innovate_uk
```

### Database Stats
```bash
# MongoDB - count by competition type
mongosh ailsa_grants --eval '
db.grants.aggregate([
  { $match: { source: "innovate_uk" } },
  { $group: { _id: "$competition_type", count: { $sum: 1 } } }
])
'

# MongoDB - grants with expected winners
mongosh ailsa_grants --eval '
db.grants.find(
  { source: "innovate_uk", expected_winners: { $ne: null } },
  { title: 1, competition_type: 1, expected_winners: 1, project_funding_max: 1 }
).sort({ expected_winners: -1 }).limit(10)
'

# Pinecone (via Python)
python3 -c "
from pinecone import Pinecone
import os
pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
index = pc.Index('ailsa-grants')
print(index.describe_index_stats())
"
```

---

## 🔧 Manual Run

```bash
# One-time run
python3 ingest_innovate_uk.py

# With bash wrapper (recommended)
./run_scraper.sh
```

---

## 📁 File Structure

```
IUK scraper/
├── .env                          # Environment variables (DO NOT COMMIT)
├── ingest_innovate_uk.py         # Main ingestion script
├── innovateuk_competition.py     # Competition scraper with retry logic
├── run_scraper.sh                # Cron runner with logging
├── setup_cron.sh                 # Interactive cron setup
├── check_scraper_health.sh       # Health check and alerting
├── test_connections.py           # Test DB connections
├── innovate_uk_urls.txt          # Competition URLs
├── mongo_setup.js                # MongoDB collection and index setup
├── logs/                         # Auto-created log directory
│   ├── scraper_YYYYMMDD_HHMMSS.log
│   ├── scraper_stats_*.json      # Run statistics
│   ├── failed_competitions_*.json # Failure tracking
│   └── cron.log
├── src/
│   ├── core/
│   │   ├── constants.py          # Configuration constants
│   │   ├── models.py             # Data models
│   │   └── domain_models.py      # Domain models
│   ├── ingest/                   # Scrapers
│   ├── normalize/                # Normalization
│   ├── monitoring/
│   │   └── scraper_stats.py      # Monitoring and failure tracking
│   ├── storage/                  # Storage utilities
│   └── index/                    # Pinecone
├── tests/
│   └── test_innovate_uk_scraper.py # Unit tests
└── DEPLOYMENT.md                 # This file
```

---

## 🆕 Competition Types

The scraper automatically detects and classifies competitions:

| Type | Detection | Examples |
|------|-----------|----------|
| **grant** | Default for standard funding | R&D grants, SBRI competitions |
| **loan** | Title/description contains "loan" | Innovation Loan Round 24 |
| **prize** | Title/description contains "prize" | Challenge prizes |

Query by type:
```sql
SELECT * FROM grants WHERE competition_type = 'loan';
```

---

## 📈 Per-Project Funding

The scraper extracts per-project funding ranges:
- `project_funding_min` - Minimum per-project funding in GBP
- `project_funding_max` - Maximum per-project funding in GBP
- `expected_winners` - Calculated using 70% of max heuristic

Example query:
```javascript
// MongoDB query
db.grants.find(
  { source: "innovate_uk", project_funding_max: { $ne: null } },
  { title: 1, project_funding_min: 1, project_funding_max: 1, expected_winners: 1, total_fund_gbp: 1 }
).sort({ expected_winners: -1 })
```

---

## 🐛 Troubleshooting

### Cron Not Running
```bash
# Check cron service
sudo systemctl status cron  # Linux
# or
sudo launchctl list | grep cron  # macOS

# Check cron logs
grep CRON /var/log/syslog  # Linux
cat /var/log/cron.log      # Some systems
```

### SSL Certificate Errors
The scraper uses `certifi` for SSL verification. If SSL errors persist:

1. Update certifi: `pip install --upgrade certifi`
2. Check the error in logs: `grep "SSL" logs/scraper_*.log`
3. Review the failed_competitions JSON for details

If a specific site has certificate issues, it will be logged but won't crash the scraper.

### Rate Limiting
Built-in rate limiting adds 1-2 second delays between requests. If you still get rate limited:
1. Increase `RATE_LIMIT_DELAY_MIN` and `RATE_LIMIT_DELAY_MAX` in `src/core/constants.py`
2. Reduce cron frequency
3. Check Innovate UK's robots.txt

### Retry Logic
The scraper automatically retries failed requests:
- **Max retries**: 3
- **Backoff factor**: 2 (exponential)
- **Retried status codes**: 429, 500, 502, 503, 504

### Database Connection Issues
```bash
# Test MongoDB connection
mongosh "$MONGO_URI" --eval "db.runCommand({ ping: 1 })"

# Test Pinecone
python3 test_connections.py

# Check MongoDB collection
mongosh ailsa_grants --eval "db.grants.getIndexes()"
```

---

## ✅ Pre-Deployment Checklist

- [ ] `.env` file configured with all API keys and MONGO_URI
- [ ] `python3 test_connections.py` passes
- [ ] MongoDB setup script run (`mongosh < mongo_setup.js`)
- [ ] Logs directory exists and is writable
- [ ] Cron job configured with correct paths
- [ ] Health check script configured with alert email

---

## ✅ Post-Deployment Validation

After running the scraper for the first time:

1. **Check success rate**:
   ```bash
   ./check_scraper_health.sh
   ```

2. **Verify database entries**:
   ```bash
   mongosh ailsa_grants --eval '
   db.grants.aggregate([
     { $match: { source: "innovate_uk" } },
     { $group: { _id: "$competition_type", count: { $sum: 1 } } }
   ])
   '
   ```

3. **Check for failures**:
   ```bash
   ls -la logs/failed_competitions_*.json
   ```

4. **Verify Pinecone**:
   ```bash
   python3 test_connections.py
   ```

---

## 🔄 Rollback Procedure

If issues occur after deployment:

1. **Stop the scraper**:
   ```bash
   pkill -f ingest_innovate_uk
   ```

2. **Revert code changes**:
   ```bash
   git checkout HEAD~1
   ```

3. **Restore database** (if needed):
   ```javascript
   // MongoDB - drop problematic fields from all documents
   db.grants.updateMany(
     {},
     { $unset: { competition_type: "", project_funding_min: "", project_funding_max: "", expected_winners: "" } }
   )
   ```

---

## 🔐 Security Notes

1. **Never commit `.env`** - Add to `.gitignore`
2. **Rotate API keys** regularly
3. **Use read-only DB user** for scraper if possible
4. **Monitor costs** - OpenAI embeddings cost money
5. **Set up alerts** for failed runs
6. **SSL verification enabled** - Uses certifi for proper certificate validation

---

## 📈 Performance

- **36 competitions**: ~5-10 minutes (with rate limiting)
- **OpenAI API**: ~$0.10 per run (embeddings)
- **Rate limiting**: 1-2 second delay between requests
- **Retry logic**: Up to 3 retries with exponential backoff
- **Deduplication**: Handled by PostgreSQL ON CONFLICT

---

## 🆘 Support

- **Logs**: `logs/scraper_*.log`
- **Stats**: `logs/scraper_stats_*.json`
- **Failures**: `logs/failed_competitions_*.json`
- **Health check**: `./check_scraper_health.sh`
- **Test connections**: `python3 test_connections.py`
- **Manual run**: `./run_scraper.sh`
- **Run tests**: `pytest tests/ -v`
