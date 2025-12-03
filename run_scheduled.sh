#!/bin/bash
# Scheduled scraper runner for cron
# Runs Tuesday and Friday at 2am UK time

# Set up environment
cd "/Users/rileycoleman/IUK scraper"

# Load environment variables
export PATH="/opt/anaconda3/bin:$PATH"

# Create timestamp for log file
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="logs/cron_${TIMESTAMP}.log"

# Ensure logs directory exists
mkdir -p logs

echo "========================================" >> "$LOG_FILE"
echo "Scraper run started at $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Step 1: Discover new competitions and add them to the URL file
echo "" >> "$LOG_FILE"
echo "--- STEP 1: Discovering new competitions ---" >> "$LOG_FILE"
python3 scripts/discover_competitions.py --update >> "$LOG_FILE" 2>&1
DISCOVER_EXIT=$?
echo "Discovery exit code: $DISCOVER_EXIT" >> "$LOG_FILE"

# Step 2: Run the main pipeline
echo "" >> "$LOG_FILE"
echo "--- STEP 2: Running main scraper pipeline ---" >> "$LOG_FILE"
python3 run_full_pipeline.py >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "========================================" >> "$LOG_FILE"
echo "Scraper run completed at $(date)" >> "$LOG_FILE"
echo "Exit code: $EXIT_CODE" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Optional: Send notification on failure
if [ $EXIT_CODE -ne 0 ]; then
    echo "Scraper failed with exit code $EXIT_CODE" >> "$LOG_FILE"
    # Uncomment below to send email notification (requires mail setup)
    # echo "Scraper failed at $(date). Check $LOG_FILE" | mail -s "IUK Scraper Alert" your@email.com
fi

exit $EXIT_CODE
