"""
Monitoring module for the Innovate UK scraper.

Provides failure tracking, statistics collection, and dead letter queue functionality.
"""

from src.monitoring.scraper_stats import ScraperMonitor, ScrapeAttempt

__all__ = ["ScraperMonitor", "ScrapeAttempt"]
