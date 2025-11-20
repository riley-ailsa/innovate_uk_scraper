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
DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

### 3. Test Connections
```bash
python3 test_connections.py
```

Should show:
- ✅ Pinecone connected
- ✅ PostgreSQL connected
- ✅ OpenAI connected

---

## 📅 Cron Scheduling

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

### View Logs
```bash
# Latest log
tail -f logs/scraper_*.log | tail -1

# All logs from today
cat logs/scraper_$(date +%Y%m%d)*.log

# Follow cron log
tail -f logs/cron.log
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
# PostgreSQL
psql $DATABASE_URL -c "SELECT COUNT(*) FROM grants WHERE source = 'innovate_uk';"

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
├── run_scraper.sh                # Cron runner with logging
├── setup_cron.sh                 # Interactive cron setup
├── test_connections.py           # Test DB connections
├── innovate_uk_urls.txt          # Competition URLs (36 total)
├── logs/                         # Auto-created log directory
│   ├── scraper_YYYYMMDD_HHMMSS.log
│   └── cron.log
├── src/
│   ├── core/                     # Data models
│   ├── ingest/                   # Scrapers
│   ├── normalize/                # Normalization
│   ├── storage/                  # PostgreSQL
│   └── index/                    # Pinecone
└── DEPLOYMENT.md                 # This file
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
The scraper uses `verify=False` for UK government sites due to certificate chain issues. This is only for the Innovate UK website scraping.

### Rate Limiting
If you get rate limited:
1. Reduce frequency in cron
2. Add delays in `ingest_innovate_uk.py`
3. Check Innovate UK's robots.txt

### Database Connection Issues
```bash
# Test PostgreSQL
psql $DATABASE_URL -c "SELECT 1;"

# Test Pinecone
python3 test_connections.py
```

---

## 🔐 Security Notes

1. **Never commit `.env`** - Add to `.gitignore`
2. **Rotate API keys** regularly
3. **Use read-only DB user** for scraper if possible
4. **Monitor costs** - OpenAI embeddings cost money
5. **Set up alerts** for failed runs

---

## 📈 Performance

- **36 competitions**: ~5-10 minutes
- **OpenAI API**: ~$0.10 per run (embeddings)
- **Logs auto-cleanup**: Keep 30 days
- **Deduplication**: Handled by PostgreSQL ON CONFLICT

---

## 🆘 Support

- Logs: `logs/scraper_*.log`
- Test: `python3 test_connections.py`
- Manual run: `./run_scraper.sh`
- Issues: Check PostgreSQL + Pinecone dashboards
