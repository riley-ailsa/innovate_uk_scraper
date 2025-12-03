"""
Scraper monitoring and statistics collection.

Provides:
- Tracking of scrape attempts (success/failure)
- Dead letter queue for failed competitions
- Statistics export for monitoring dashboards
- Failure analysis and alerting thresholds
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from src.core.constants import FAILURE_THRESHOLD, MAX_FAILED_COMPETITIONS

logger = logging.getLogger(__name__)


@dataclass
class ScrapeAttempt:
    """
    Record of a single scrape attempt.

    Attributes:
        competition_id: Unique identifier for the competition
        url: URL that was scraped
        timestamp: When the attempt was made
        success: Whether the scrape succeeded
        error: Error message if failed
        error_type: Type of error (network, parsing, etc.)
        retry_count: Number of retries attempted
        duration_ms: Time taken for the scrape in milliseconds
    """
    competition_id: str
    url: str
    timestamp: datetime
    success: bool
    error: Optional[str] = None
    error_type: Optional[str] = None
    retry_count: int = 0
    duration_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "competition_id": self.competition_id,
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "error": self.error,
            "error_type": self.error_type,
            "retry_count": self.retry_count,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ScrapeStats:
    """
    Aggregate statistics for a scrape run.

    Attributes:
        run_id: Unique identifier for this run
        start_time: When the run started
        end_time: When the run ended
        total_competitions: Total number of competitions processed
        successful: Number of successful scrapes
        failed: Number of failed scrapes
        new_competitions: Number of new competitions discovered
        updated_competitions: Number of competitions with changes
        unchanged_competitions: Number of competitions without changes
        total_retries: Total retry attempts across all competitions
    """
    run_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_competitions: int = 0
    successful: int = 0
    failed: int = 0
    new_competitions: int = 0
    updated_competitions: int = 0
    unchanged_competitions: int = 0
    total_retries: int = 0

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_competitions == 0:
            return 0.0
        return (self.successful / self.total_competitions) * 100

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate run duration in seconds."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "run_id": self.run_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_competitions": self.total_competitions,
            "successful": self.successful,
            "failed": self.failed,
            "new_competitions": self.new_competitions,
            "updated_competitions": self.updated_competitions,
            "unchanged_competitions": self.unchanged_competitions,
            "total_retries": self.total_retries,
            "success_rate": round(self.success_rate, 2),
            "duration_seconds": self.duration_seconds,
        }


class ScraperMonitor:
    """
    Monitor scraper health and track failures.

    Features:
    - Track all scrape attempts
    - Maintain dead letter queue for persistent failures
    - Generate statistics for monitoring
    - Export failures for manual review

    Usage:
        monitor = ScraperMonitor()

        # Log each attempt
        monitor.log_attempt(
            competition_id="2341",
            url="https://...",
            success=True
        )

        # At end of run
        stats = monitor.get_stats()
        monitor.export_failures("failed_competitions.json")
    """

    def __init__(self, run_id: Optional[str] = None):
        """
        Initialize the monitor.

        Args:
            run_id: Optional identifier for this run. Defaults to timestamp.
        """
        self.run_id = run_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.attempts: List[ScrapeAttempt] = []
        self.failed_competitions: Dict[str, int] = {}  # id -> failure_count
        self.stats = ScrapeStats(
            run_id=self.run_id,
            start_time=datetime.utcnow()
        )

        logger.info(f"ScraperMonitor initialized with run_id: {self.run_id}")

    def log_attempt(
        self,
        competition_id: str,
        url: str,
        success: bool,
        error: Optional[str] = None,
        error_type: Optional[str] = None,
        retry_count: int = 0,
        duration_ms: Optional[int] = None,
        is_new: bool = False,
        has_changes: bool = False,
    ) -> None:
        """
        Log a scrape attempt.

        Args:
            competition_id: Competition identifier
            url: URL that was scraped
            success: Whether scrape succeeded
            error: Error message if failed
            error_type: Category of error (network, parsing, ssl, unknown)
            retry_count: Number of retries performed
            duration_ms: Time taken in milliseconds
            is_new: Whether this is a newly discovered competition
            has_changes: Whether the competition had changes from last scrape
        """
        attempt = ScrapeAttempt(
            competition_id=competition_id,
            url=url,
            timestamp=datetime.utcnow(),
            success=success,
            error=error,
            error_type=error_type,
            retry_count=retry_count,
            duration_ms=duration_ms,
        )

        self.attempts.append(attempt)
        self.stats.total_competitions += 1
        self.stats.total_retries += retry_count

        if success:
            self.stats.successful += 1
            if is_new:
                self.stats.new_competitions += 1
            elif has_changes:
                self.stats.updated_competitions += 1
            else:
                self.stats.unchanged_competitions += 1

            # Clear from failed queue if previously failed
            if competition_id in self.failed_competitions:
                del self.failed_competitions[competition_id]
                logger.info(f"Competition {competition_id} recovered from failures")
        else:
            self.stats.failed += 1

            # Track in dead letter queue
            current_failures = self.failed_competitions.get(competition_id, 0)
            self.failed_competitions[competition_id] = current_failures + 1

            # Log warning if exceeds threshold
            if self.failed_competitions[competition_id] >= FAILURE_THRESHOLD:
                logger.warning(
                    f"Competition {competition_id} has failed {self.failed_competitions[competition_id]} times - "
                    f"flagged for manual review"
                )

            # Trim dead letter queue if too large
            if len(self.failed_competitions) > MAX_FAILED_COMPETITIONS:
                # Remove oldest entries (those with lowest failure counts)
                sorted_failures = sorted(
                    self.failed_competitions.items(),
                    key=lambda x: x[1],
                    reverse=True
                )
                self.failed_competitions = dict(sorted_failures[:MAX_FAILED_COMPETITIONS])

    def get_failed_competitions(self, min_failures: int = FAILURE_THRESHOLD) -> Dict[str, int]:
        """
        Get competitions that have failed multiple times.

        Args:
            min_failures: Minimum failure count to include

        Returns:
            Dict mapping competition_id to failure count
        """
        return {
            comp_id: count
            for comp_id, count in self.failed_competitions.items()
            if count >= min_failures
        }

    def get_recent_failures(self, limit: int = 10) -> List[ScrapeAttempt]:
        """
        Get most recent failed attempts.

        Args:
            limit: Maximum number of failures to return

        Returns:
            List of failed ScrapeAttempt objects
        """
        failed = [a for a in self.attempts if not a.success]
        return failed[-limit:]

    def get_error_summary(self) -> Dict[str, int]:
        """
        Get summary of errors by type.

        Returns:
            Dict mapping error_type to count
        """
        summary: Dict[str, int] = {}
        for attempt in self.attempts:
            if not attempt.success and attempt.error_type:
                summary[attempt.error_type] = summary.get(attempt.error_type, 0) + 1
        return summary

    def finalize(self) -> ScrapeStats:
        """
        Finalize the run and return statistics.

        Call this at the end of a scrape run.

        Returns:
            Final ScrapeStats object
        """
        self.stats.end_time = datetime.utcnow()

        logger.info(
            f"Scrape run {self.run_id} complete: "
            f"{self.stats.successful}/{self.stats.total_competitions} successful "
            f"({self.stats.success_rate:.1f}%)"
        )

        return self.stats

    def get_stats(self) -> ScrapeStats:
        """
        Get current statistics (without finalizing).

        Returns:
            Current ScrapeStats object
        """
        return self.stats

    def export_failures(self, output_path: str) -> None:
        """
        Export failed competitions to JSON file for manual review.

        Args:
            output_path: Path to output file
        """
        path = Path(output_path)

        # Collect detailed failure information
        failures = []
        for attempt in self.attempts:
            if not attempt.success:
                failures.append(attempt.to_dict())

        # Build export data
        export_data = {
            "run_id": self.run_id,
            "export_time": datetime.utcnow().isoformat(),
            "summary": {
                "total_failures": len(failures),
                "persistent_failures": len(self.get_failed_competitions()),
                "error_summary": self.get_error_summary(),
            },
            "persistent_failures": self.get_failed_competitions(),
            "all_failures": failures,
        }

        # Write to file
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(export_data, f, indent=2)

        logger.info(f"Exported {len(failures)} failures to {output_path}")

    def export_stats(self, output_path: str) -> None:
        """
        Export run statistics to JSON file.

        Args:
            output_path: Path to output file
        """
        path = Path(output_path)

        export_data = {
            "stats": self.stats.to_dict(),
            "error_summary": self.get_error_summary(),
            "persistent_failures_count": len(self.get_failed_competitions()),
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(export_data, f, indent=2)

        logger.info(f"Exported stats to {output_path}")

    def should_alert(self) -> bool:
        """
        Check if current state warrants an alert.

        Returns True if:
        - Success rate is below 95%
        - More than 3 competitions have persistent failures

        Returns:
            True if alerting is recommended
        """
        if self.stats.total_competitions == 0:
            return False

        # Alert if success rate below 95%
        if self.stats.success_rate < 95:
            return True

        # Alert if too many persistent failures
        if len(self.get_failed_competitions()) > 3:
            return True

        return False

    def get_alert_message(self) -> Optional[str]:
        """
        Generate alert message if alerting is warranted.

        Returns:
            Alert message string or None
        """
        if not self.should_alert():
            return None

        messages = []

        if self.stats.success_rate < 95:
            messages.append(
                f"Low success rate: {self.stats.success_rate:.1f}% "
                f"({self.stats.failed}/{self.stats.total_competitions} failed)"
            )

        persistent = self.get_failed_competitions()
        if len(persistent) > 3:
            messages.append(
                f"{len(persistent)} competitions have persistent failures"
            )

        error_summary = self.get_error_summary()
        if error_summary:
            top_error = max(error_summary.items(), key=lambda x: x[1])
            messages.append(f"Most common error: {top_error[0]} ({top_error[1]} occurrences)")

        return "\n".join(messages)
