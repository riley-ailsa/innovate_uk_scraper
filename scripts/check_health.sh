#!/bin/bash
#
# Innovate UK Scraper Health Check Script
#
# Checks the last run status and alerts if there are failures.
# Designed to be run via cron after the scraper.
#
# Usage:
#   ./check_scraper_health.sh
#   ./check_scraper_health.sh --email admin@example.com
#
# Exit codes:
#   0 - Healthy
#   1 - Unhealthy (failures detected)
#   2 - Error (could not check)

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
FAILURE_THRESHOLD=3
EMAIL_RECIPIENT="${1:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Find the most recent stats file
get_latest_stats_file() {
    local latest=$(ls -t "${LOG_DIR}"/scraper_stats_*.json 2>/dev/null | head -1)
    echo "$latest"
}

# Find the most recent log file
get_latest_log_file() {
    local latest=$(ls -t "${LOG_DIR}"/scraper_*.log 2>/dev/null | head -1)
    echo "$latest"
}

# Count errors in log file
count_errors() {
    local log_file="$1"
    local count=$(grep -c "ERROR" "$log_file" 2>/dev/null || echo "0")
    echo "$count"
}

# Count specific error pattern
count_error_pattern() {
    local log_file="$1"
    local pattern="$2"
    local count=$(grep -c "$pattern" "$log_file" 2>/dev/null || echo "0")
    echo "$count"
}

# Parse JSON stats file (requires jq or Python)
parse_stats() {
    local stats_file="$1"
    local key="$2"

    if command -v jq &> /dev/null; then
        jq -r ".$key // empty" "$stats_file" 2>/dev/null
    elif command -v python3 &> /dev/null; then
        python3 -c "import json; print(json.load(open('$stats_file')).get('stats', {}).get('$key', ''))" 2>/dev/null
    else
        echo ""
    fi
}

# Send alert email
send_alert() {
    local subject="$1"
    local body="$2"
    local recipient="$3"

    if [ -n "$recipient" ]; then
        if command -v mail &> /dev/null; then
            echo "$body" | mail -s "$subject" "$recipient"
            log_info "Alert sent to $recipient"
        else
            log_warn "mail command not available, cannot send email"
        fi
    fi
}

# Main health check
main() {
    echo "=========================================="
    echo "Innovate UK Scraper Health Check"
    echo "=========================================="
    echo ""

    # Check if logs directory exists
    if [ ! -d "$LOG_DIR" ]; then
        log_error "Logs directory not found: $LOG_DIR"
        exit 2
    fi

    # Find latest stats file
    STATS_FILE=$(get_latest_stats_file)
    LOG_FILE=$(get_latest_log_file)

    if [ -z "$STATS_FILE" ]; then
        log_warn "No stats files found in $LOG_DIR"
        log_info "Checking log files instead..."
    else
        log_info "Latest stats: $STATS_FILE"
    fi

    if [ -z "$LOG_FILE" ]; then
        log_error "No log files found in $LOG_DIR"
        exit 2
    fi

    log_info "Latest log: $LOG_FILE"
    echo ""

    # Initialize health status
    HEALTHY=true
    ALERT_MESSAGES=""

    # Check 1: Error count in logs
    ERROR_COUNT=$(count_errors "$LOG_FILE")
    log_info "Errors in log: $ERROR_COUNT"

    if [ "$ERROR_COUNT" -gt "$FAILURE_THRESHOLD" ]; then
        HEALTHY=false
        ALERT_MESSAGES="${ALERT_MESSAGES}\n- High error count: $ERROR_COUNT errors"
    fi

    # Check 2: SSL errors
    SSL_ERRORS=$(count_error_pattern "$LOG_FILE" "SSL")
    if [ "$SSL_ERRORS" -gt 0 ]; then
        log_warn "SSL errors detected: $SSL_ERRORS"
        ALERT_MESSAGES="${ALERT_MESSAGES}\n- SSL errors: $SSL_ERRORS"
    fi

    # Check 3: Network errors
    NETWORK_ERRORS=$(count_error_pattern "$LOG_FILE" "Network error")
    if [ "$NETWORK_ERRORS" -gt 0 ]; then
        log_warn "Network errors detected: $NETWORK_ERRORS"
    fi

    # Check 4: Parse stats file if available
    if [ -n "$STATS_FILE" ] && [ -f "$STATS_FILE" ]; then
        echo ""
        log_info "Parsing stats file..."

        SUCCESS_RATE=$(parse_stats "$STATS_FILE" "success_rate")
        TOTAL=$(parse_stats "$STATS_FILE" "total_competitions")
        FAILED=$(parse_stats "$STATS_FILE" "failed")

        if [ -n "$SUCCESS_RATE" ]; then
            log_info "Success rate: ${SUCCESS_RATE}%"

            # Check if success rate is below 95%
            if command -v bc &> /dev/null; then
                IS_LOW=$(echo "$SUCCESS_RATE < 95" | bc -l)
                if [ "$IS_LOW" -eq 1 ]; then
                    HEALTHY=false
                    ALERT_MESSAGES="${ALERT_MESSAGES}\n- Low success rate: ${SUCCESS_RATE}%"
                fi
            fi
        fi

        if [ -n "$TOTAL" ]; then
            log_info "Total competitions: $TOTAL"
        fi

        if [ -n "$FAILED" ] && [ "$FAILED" -gt 0 ]; then
            log_warn "Failed competitions: $FAILED"
        fi
    fi

    # Check 5: Look for persistent failures file
    FAILURES_FILE=$(ls -t "${LOG_DIR}"/failed_competitions_*.json 2>/dev/null | head -1)
    if [ -n "$FAILURES_FILE" ] && [ -f "$FAILURES_FILE" ]; then
        log_warn "Failures file exists: $FAILURES_FILE"

        # Count persistent failures
        if command -v jq &> /dev/null; then
            PERSISTENT_COUNT=$(jq '.persistent_failures | length' "$FAILURES_FILE" 2>/dev/null || echo "0")
            if [ "$PERSISTENT_COUNT" -gt 0 ]; then
                log_warn "Persistent failures: $PERSISTENT_COUNT competitions"
                ALERT_MESSAGES="${ALERT_MESSAGES}\n- Persistent failures: $PERSISTENT_COUNT competitions need manual review"
            fi
        fi
    fi

    echo ""
    echo "=========================================="

    # Final status
    if [ "$HEALTHY" = true ]; then
        log_info "Status: HEALTHY"
        echo "=========================================="
        exit 0
    else
        log_error "Status: UNHEALTHY"
        echo ""
        echo -e "Issues detected:${ALERT_MESSAGES}"
        echo ""
        echo "=========================================="

        # Send alert if email provided
        if [ -n "$EMAIL_RECIPIENT" ]; then
            ALERT_SUBJECT="[ALERT] Innovate UK Scraper Health Check Failed"
            ALERT_BODY="The Innovate UK scraper health check has detected issues:\n${ALERT_MESSAGES}\n\nPlease review the logs at: $LOG_FILE"
            send_alert "$ALERT_SUBJECT" "$ALERT_BODY" "$EMAIL_RECIPIENT"
        fi

        exit 1
    fi
}

# Handle arguments
case "${1:-}" in
    --help|-h)
        echo "Usage: $0 [--email recipient@example.com]"
        echo ""
        echo "Options:"
        echo "  --email EMAIL   Send alert email to this address if unhealthy"
        echo "  --help          Show this help message"
        exit 0
        ;;
    --email)
        EMAIL_RECIPIENT="${2:-}"
        if [ -z "$EMAIL_RECIPIENT" ]; then
            log_error "Email address required with --email flag"
            exit 2
        fi
        ;;
esac

# Run main function
main
