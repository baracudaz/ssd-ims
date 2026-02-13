"""Helper utilities for SSD IMS integration."""

import re
from datetime import datetime, timedelta, timezone


def calculate_yesterday_range(now: datetime) -> tuple[datetime, datetime]:
    """Calculate date range for yesterday in the API-expected format."""
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    period_start = today_midnight - timedelta(days=1)
    period_end = today_midnight.astimezone(timezone.utc)
    return period_start, period_end


def sanitize_name(name: str, *, lower: bool = True) -> str:
    """Sanitize a name for use in identifiers."""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized.lower() if lower else sanitized
