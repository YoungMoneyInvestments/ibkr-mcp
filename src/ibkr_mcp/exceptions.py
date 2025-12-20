"""
Custom exceptions for IBKR MCP Server.
"""


class IBKRMCPError(Exception):
    """Base exception for IBKR MCP Server."""
    pass


class ConnectionError(IBKRMCPError):
    """Connection-related errors."""
    pass


class OrderError(IBKRMCPError):
    """Order-related errors."""
    pass


class MarketDataError(IBKRMCPError):
    """Market data errors."""
    pass


class DataError(IBKRMCPError):
    """Data retrieval/processing errors."""
    pass


class RateLimitError(IBKRMCPError):
    """Rate limit exceeded."""
    pass


class ValidationError(IBKRMCPError):
    """Input validation errors."""
    pass


class CircuitBreakerError(IBKRMCPError):
    """Circuit breaker tripped."""
    pass
