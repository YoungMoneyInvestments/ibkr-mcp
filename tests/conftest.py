"""Pytest configuration and fixtures."""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from ibkr_mcp.config import ServerConfig, IBKRConfig, MCPConfig, RiskConfig


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def ibkr_config():
    """Create test IBKR config."""
    return IBKRConfig(
        host="127.0.0.1",
        port=7497,
        client_id=99,  # Use different client ID for tests
        timeout=10,
        readonly=True,  # Read-only for safety
    )


@pytest.fixture
def server_config(ibkr_config):
    """Create test server config."""
    return ServerConfig(
        ibkr=ibkr_config,
        mcp=MCPConfig(transport="stdio"),
        risk=RiskConfig(),
    )


@pytest.fixture
def mock_ib():
    """Create mock IB connection."""
    mock = MagicMock()
    mock.isConnected.return_value = True
    mock.connectAsync = AsyncMock()
    mock.disconnect = MagicMock()
    mock.qualifyContracts = MagicMock(return_value=[MagicMock()])
    mock.reqMktData = MagicMock()
    mock.cancelMktData = MagicMock()
    mock.positions = MagicMock(return_value=[])
    mock.accountSummary = MagicMock(return_value=[])
    mock.openTrades = MagicMock(return_value=[])
    return mock
