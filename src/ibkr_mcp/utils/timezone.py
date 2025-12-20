"""
Timezone utilities for market time handling.
"""

from datetime import datetime
from typing import Optional

import pytz


# Default market timezone
DEFAULT_MARKET_TIMEZONE = "America/New_York"


def get_market_time(timezone: str = DEFAULT_MARKET_TIMEZONE) -> datetime:
    """
    Get current time in market timezone.

    Args:
        timezone: Market timezone (default: America/New_York)

    Returns:
        Current datetime in market timezone
    """
    tz = pytz.timezone(timezone)
    return datetime.now(tz)


def get_local_time() -> datetime:
    """Get current local time."""
    return datetime.now()


def to_market_time(
    dt: datetime,
    from_timezone: Optional[str] = None,
    to_timezone: str = DEFAULT_MARKET_TIMEZONE,
) -> datetime:
    """
    Convert datetime to market timezone.

    Args:
        dt: Datetime to convert
        from_timezone: Source timezone (None = local)
        to_timezone: Target market timezone

    Returns:
        Datetime in market timezone
    """
    # Make aware if naive
    if dt.tzinfo is None:
        if from_timezone:
            tz = pytz.timezone(from_timezone)
            dt = tz.localize(dt)
        else:
            dt = pytz.utc.localize(dt)

    # Convert to market timezone
    market_tz = pytz.timezone(to_timezone)
    return dt.astimezone(market_tz)


def is_market_open(timezone: str = DEFAULT_MARKET_TIMEZONE) -> bool:
    """
    Check if US stock market is currently open.

    Note: This is a simple check based on time only.
    Does not account for holidays.

    Args:
        timezone: Market timezone

    Returns:
        True if market is open
    """
    now = get_market_time(timezone)

    # Check weekday (0=Monday, 6=Sunday)
    if now.weekday() >= 5:  # Weekend
        return False

    # Market hours: 9:30 AM - 4:00 PM ET
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

    return market_open <= now <= market_close


def get_market_status(timezone: str = DEFAULT_MARKET_TIMEZONE) -> dict:
    """
    Get detailed market status.

    Args:
        timezone: Market timezone

    Returns:
        Dict with market status info
    """
    now = get_market_time(timezone)
    is_open = is_market_open(timezone)

    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

    if is_open:
        time_to_close = (market_close - now).total_seconds() / 60
        status = "open"
    elif now < market_open:
        time_to_open = (market_open - now).total_seconds() / 60
        status = "pre_market"
    else:
        status = "closed"
        time_to_open = None

    return {
        "status": status,
        "is_open": is_open,
        "current_time": now.isoformat(),
        "timezone": timezone,
        "market_open_time": "09:30",
        "market_close_time": "16:00",
        "minutes_to_close": time_to_close if is_open else None,
        "is_weekend": now.weekday() >= 5,
    }
