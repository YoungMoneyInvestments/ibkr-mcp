"""
IBKR MCP Server - Full-featured Interactive Brokers integration for AI assistants.

Features:
- Account management and portfolio analysis
- Order placement (market, limit, stop, bracket, trailing, OCA, algo)
- Real-time and historical market data
- Options chain and spread analysis
- Futures chain and rollover detection
- Market scanners
- Risk management and VaR calculation
- Circuit breaker for automated trading
"""

__version__ = "1.0.0"
__author__ = "Cameron Bennion"

from .config import ServerConfig, IBKRConfig
from .client import IBKRClient
from .exceptions import (
    IBKRMCPError,
    ConnectionError,
    OrderError,
    MarketDataError,
    DataError,
)

__all__ = [
    "ServerConfig",
    "IBKRConfig",
    "IBKRClient",
    "IBKRMCPError",
    "ConnectionError",
    "OrderError",
    "MarketDataError",
    "DataError",
]
