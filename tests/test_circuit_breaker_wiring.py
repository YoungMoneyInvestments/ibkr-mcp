"""Tests for circuit breaker wiring into order execution path."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from ibkr_mcp.config import ServerConfig, IBKRConfig, MCPConfig, RiskConfig
from ibkr_mcp.server import IBKRMCPServer
from ibkr_mcp.utils.circuit_breaker import TradingCircuitBreaker


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def risk_config():
    """Create risk config with tight limits for testing."""
    return RiskConfig(
        max_loss_per_minute=100.0,
        max_trades_per_minute=5,
        max_daily_loss=500.0,
        max_position_size=1000.0,
    )


@pytest.fixture
def server_config(risk_config):
    """Create test server config with risk config."""
    return ServerConfig(
        ibkr=IBKRConfig(
            host="127.0.0.1",
            port=7497,
            client_id=99,
            timeout=10,
            readonly=False,
        ),
        mcp=MCPConfig(transport="stdio"),
        risk=risk_config,
    )


@pytest.fixture
def server(server_config):
    """Create server instance with mocked client and FastMCP."""
    with patch("ibkr_mcp.server.IBKRClient") as mock_client_cls, \
         patch("ibkr_mcp.server.FastMCP") as mock_fastmcp_cls:
        mock_client = MagicMock()
        mock_client.register_event_handler = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_mcp = MagicMock()
        mock_mcp.tool = MagicMock(return_value=lambda f: f)
        mock_fastmcp_cls.return_value = mock_mcp

        srv = IBKRMCPServer(server_config)
        srv.client = mock_client
        return srv


# =============================================================================
# Initialization Tests
# =============================================================================


class TestCircuitBreakerInitialization:
    """Test that circuit breaker is properly instantiated from config."""

    def test_circuit_breaker_created(self, server):
        """Circuit breaker should be instantiated on server init."""
        assert hasattr(server, "circuit_breaker")
        assert isinstance(server.circuit_breaker, TradingCircuitBreaker)

    def test_circuit_breaker_limits_from_config(self, server, risk_config):
        """Circuit breaker limits should match risk config values."""
        cb = server.circuit_breaker
        assert cb.max_loss_per_minute == risk_config.max_loss_per_minute
        assert cb.max_trades_per_minute == risk_config.max_trades_per_minute
        assert cb.max_daily_loss == risk_config.max_daily_loss
        assert cb.max_position_size == risk_config.max_position_size

    def test_event_handler_registered(self, server):
        """Order status event handler should be registered on client."""
        server.client.register_event_handler.assert_called_once_with(
            "order_status", server._on_order_status
        )


# =============================================================================
# Trade Value Estimation Tests
# =============================================================================


class TestEstimateTradeValue:
    """Test trade value estimation for circuit breaker checks."""

    def test_with_limit_price(self, server):
        value = server._estimate_trade_value(100, limit_price=50.0)
        assert value == 5000.0

    def test_with_stop_price(self, server):
        value = server._estimate_trade_value(100, stop_price=45.0)
        assert value == 4500.0

    def test_with_entry_price(self, server):
        value = server._estimate_trade_value(100, entry_price=55.0)
        assert value == 5500.0

    def test_limit_price_takes_precedence(self, server):
        value = server._estimate_trade_value(100, limit_price=50.0, stop_price=45.0)
        assert value == 5000.0

    def test_market_order_returns_zero(self, server):
        value = server._estimate_trade_value(100)
        assert value == 0.0

    def test_negative_quantity_uses_abs(self, server):
        value = server._estimate_trade_value(-100, limit_price=50.0)
        assert value == 5000.0


# =============================================================================
# Circuit Breaker Check Tests
# =============================================================================


class TestCheckCircuitBreaker:
    """Test circuit breaker pre-trade validation."""

    def test_allows_normal_trade(self, server):
        result = server._check_circuit_breaker(500.0)
        assert result is None

    def test_blocks_oversized_trade(self, server):
        """Trade exceeding max_position_size should be blocked."""
        result = server._check_circuit_breaker(2000.0)
        assert result is not None
        assert result["success"] is False
        assert "Circuit breaker" in result["error"]
        assert "Position size" in result["error"]

    def test_blocks_when_tripped(self, server):
        """All trades should be blocked when breaker is tripped."""
        server.circuit_breaker.trip("test trip")
        result = server._check_circuit_breaker(100.0)
        assert result is not None
        assert result["success"] is False
        assert "tripped" in result["error"]

    def test_blocks_excessive_trade_rate(self, server):
        """Should block after exceeding max_trades_per_minute."""
        # max_trades_per_minute is 5 for test config
        for _ in range(5):
            result = server._check_circuit_breaker(100.0)
            assert result is None

        # 6th trade should be blocked
        result = server._check_circuit_breaker(100.0)
        assert result is not None
        assert result["success"] is False
        assert "Too many trades" in result["error"]


# =============================================================================
# Fill Callback Tests
# =============================================================================


class TestFillCallback:
    """Test P&L recording from order fill events."""

    def test_records_commission_on_fill(self, server):
        """Commission should be recorded as negative P&L on fill."""
        event_data = {
            "status": "Filled",
            "filled": 100,
            "avg_fill_price": 50.0,
            "action": "BUY",
            "commission": 1.50,
        }
        server._on_order_status(event_data)
        assert server.circuit_breaker.daily_pnl == -1.50

    def test_ignores_non_filled_status(self, server):
        """Non-filled events should not record P&L."""
        event_data = {
            "status": "Submitted",
            "filled": 0,
            "avg_fill_price": 0,
            "action": "BUY",
            "commission": None,
        }
        server._on_order_status(event_data)
        assert server.circuit_breaker.daily_pnl == 0.0

    def test_handles_missing_commission(self, server):
        """Fill without commission data should not crash."""
        event_data = {
            "status": "Filled",
            "filled": 100,
            "avg_fill_price": 50.0,
            "action": "BUY",
            "commission": None,
        }
        server._on_order_status(event_data)
        assert server.circuit_breaker.daily_pnl == 0.0

    def test_handles_malformed_event(self, server):
        """Malformed event data should not crash."""
        server._on_order_status({})
        server._on_order_status({"status": "Filled"})
        assert server.circuit_breaker.daily_pnl == 0.0


# =============================================================================
# Circuit Breaker Status/Reset Tests
# =============================================================================


class TestCircuitBreakerStatus:
    """Test the circuit breaker status reporting."""

    def test_status_returns_all_fields(self, server):
        status = server.circuit_breaker.get_status()
        assert "is_tripped" in status
        assert "trip_reason" in status
        assert "trip_count" in status
        assert "daily_pnl" in status
        assert "trades_last_minute" in status
        assert "loss_last_minute" in status
        assert "limits" in status
        assert "utilization" in status

    def test_status_reflects_trip(self, server):
        server.circuit_breaker.trip("test reason")
        status = server.circuit_breaker.get_status()
        assert status["is_tripped"] is True
        assert status["trip_reason"] == "test reason"
        assert status["trip_count"] == 1


class TestCircuitBreakerReset:
    """Test the circuit breaker reset mechanism."""

    def test_reset_clears_trip(self, server):
        server.circuit_breaker.trip("test")
        success = server.circuit_breaker.reset()
        assert success is True
        assert server.circuit_breaker.is_tripped is False

    def test_reset_blocked_after_three_trips(self, server):
        for _ in range(3):
            server.circuit_breaker.trip("repeated issue")
            server.circuit_breaker.is_tripped = False

        server.circuit_breaker.trip("fourth trip")
        success = server.circuit_breaker.reset()
        assert success is False
        assert server.circuit_breaker.is_tripped is True

    def test_admin_override_reset(self, server):
        for _ in range(3):
            server.circuit_breaker.trip("repeated issue")
            server.circuit_breaker.is_tripped = False

        server.circuit_breaker.trip("fourth trip")
        success = server.circuit_breaker.reset(admin_override=True)
        assert success is True
        assert server.circuit_breaker.is_tripped is False


# =============================================================================
# Integration: Order Tools Block When Tripped
# =============================================================================


class TestOrderToolsCircuitBreakerIntegration:
    """Verify that order tools respect circuit breaker state."""

    def test_tripped_breaker_blocks_all_orders(self, server):
        """When tripped, _check_circuit_breaker should block regardless of value."""
        server.circuit_breaker.trip("daily loss exceeded")

        # Even a $0 trade value should be blocked when tripped
        result = server._check_circuit_breaker(0.0)
        assert result is not None
        assert result["success"] is False

    def test_position_size_limit_enforced(self, server):
        """Trades exceeding position size limit should be blocked."""
        # max_position_size is 1000 in test config
        result = server._check_circuit_breaker(1001.0)
        assert result is not None
        assert result["success"] is False
        assert "Position size" in result["error"]

    def test_under_limit_trade_allowed(self, server):
        result = server._check_circuit_breaker(999.0)
        assert result is None

    def test_zero_value_trade_allowed(self, server):
        """Market orders (value=0) should pass position size check."""
        result = server._check_circuit_breaker(0.0)
        assert result is None


# =============================================================================
# Daily P&L Tracking Integration
# =============================================================================


class TestDailyPnlTracking:
    """Test that P&L accumulates and triggers circuit breaker."""

    def test_cumulative_commission_tracking(self, server):
        """Multiple fills should accumulate commission costs."""
        for i in range(3):
            server._on_order_status({
                "status": "Filled",
                "filled": 100,
                "avg_fill_price": 50.0,
                "action": "BUY",
                "commission": 1.50,
            })
        assert server.circuit_breaker.daily_pnl == pytest.approx(-4.50)

    def test_large_loss_trips_breaker(self, server):
        """Recording large loss via record_pnl should trip breaker."""
        # max_daily_loss is 500 in test config
        server.circuit_breaker.record_pnl(-600.0)
        assert server.circuit_breaker.is_tripped is True
        assert "Daily loss" in server.circuit_breaker.trip_reason
