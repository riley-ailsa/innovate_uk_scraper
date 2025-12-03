# Cron Setup for Innovate UK Scraper

## Schedule: Tuesday and Friday at 2:00 AM

### Option 1: Using crontab (macOS/Linux)

1. **Grant Full Disk Access to cron** (macOS only):
   - Open System Preferences → Security & Privacy → Privacy
   - Select "Full Disk Access" from the left sidebar
   - Click the lock icon and authenticate
   - Click "+" and add `/usr/sbin/cron`

2. **Edit your crontab**:
   ```bash
   crontab -e
   ```

3. **Add this line** (runs at 2:00 AM on Tuesday and Friday):
   ```
   0 2 * * 2,5 /Users/rileycoleman/IUK\ scraper/run_scheduled.sh
   ```

4. **Save and exit** (in vim: press `Esc`, type `:wq`, press `Enter`)

5. **Verify the cron job**:
   ```bash
   crontab -l
   ```

### Option 2: Using launchd (macOS recommended)

Create a launch agent for more reliable scheduling on macOS:

1. **Create the plist file**:
   ```bash
   nano ~/Library/LaunchAgents/com.iuk.scraper.plist
   ```

2. **Paste this content**:
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
       <key>Label</key>
       <string>com.iuk.scraper</string>
       <key>ProgramArguments</key>
       <array>
           <string>/Users/rileycoleman/IUK scraper/run_scheduled.sh</string>
       </array>
       <key>StartCalendarInterval</key>
       <array>
           <!-- Tuesday at 2:00 AM -->
           <dict>
               <key>Weekday</key>
               <integer>2</integer>
               <key>Hour</key>
               <integer>2</integer>
               <key>Minute</key>
               <integer>0</integer>
           </dict>
           <!-- Friday at 2:00 AM -->
           <dict>
               <key>Weekday</key>
               <integer>5</integer>
               <key>Hour</key>
               <integer>2</integer>
               <key>Minute</key>
               <integer>0</integer>
           </dict>
       </array>
       <key>StandardOutPath</key>
       <string>/Users/rileycoleman/IUK scraper/logs/launchd_stdout.log</string>
       <key>StandardErrorPath</key>
       <string>/Users/rileycoleman/IUK scraper/logs/launchd_stderr.log</string>
       <key>EnvironmentVariables</key>
       <dict>
           <key>PATH</key>
           <string>/opt/anaconda3/bin:/usr/local/bin:/usr/bin:/bin</string>
       </dict>
   </dict>
   </plist>
   ```

3. **Load the launch agent**:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.iuk.scraper.plist
   ```

4. **Verify it's loaded**:
   ```bash
   launchctl list | grep iuk
   ```

5. **To test manually**:
   ```bash
   launchctl start com.iuk.scraper
   ```

### Cron Time Reference

```
# ┌───────────── minute (0 - 59)
# │ ┌───────────── hour (0 - 23)
# │ │ ┌───────────── day of month (1 - 31)
# │ │ │ ┌───────────── month (1 - 12)
# │ │ │ │ ┌───────────── day of week (0 - 6) (Sunday = 0)
# │ │ │ │ │
# * * * * * command
  0 2 * * 2,5 /path/to/script  # 2am on Tuesday (2) and Friday (5)
```

### Troubleshooting

1. **Check if cron service is running**:
   ```bash
   sudo launchctl list | grep cron
   ```

2. **View cron logs (macOS)**:
   ```bash
   log show --predicate 'process == "cron"' --last 1h
   ```

3. **Test the script manually first**:
   ```bash
   cd "/Users/rileycoleman/IUK scraper"
   ./run_scheduled.sh
   ```

4. **Check script logs**:
   ```bash
   ls -la "/Users/rileycoleman/IUK scraper/logs/"
   tail -100 "/Users/rileycoleman/IUK scraper/logs/cron_*.log"
   ```

### Alternative: GitHub Actions (Cloud-based)

If you prefer cloud-based scheduling, you can use GitHub Actions:

```yaml
# .github/workflows/scraper.yml
name: Innovate UK Scraper

on:
  schedule:
    # Runs at 2:00 AM UTC on Tuesday and Friday
    - cron: '0 2 * * 2,5'
  workflow_dispatch:  # Allow manual trigger

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: python run_full_pipeline.py
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          PINECONE_API_KEY: ${{ secrets.PINECONE_API_KEY }}
          MONGODB_URI: ${{ secrets.MONGODB_URI }}
```
