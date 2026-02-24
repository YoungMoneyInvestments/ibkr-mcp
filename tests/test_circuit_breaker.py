"""Tests for TradingCircuitBreaker."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from ibkr_mcp.utils.circuit_breaker import TradingCircuitBreaker


class TestCircuitBreakerInit:
    """Test circuit breaker initialization."""

    def test_default_limits(self):
        cb = TradingCircuitBreaker()
        assert cb.max_loss_per_minute == 1000
        assert cb.max_trades_per_minute == 50
        assert cb.max_daily_loss == 5000
        assert cb.max_position_size == 10000

    def test_custom_limits(self):
        cb = TradingCircuitBreaker(
            max_loss_per_minute=500,
            max_trades_per_minute=10,
            max_daily_loss=2000,
            max_position_size=5000,
        )
        assert cb.max_loss_per_minute == 500
        assert cb.max_trades_per_minute == 10
        assert cb.max_daily_loss == 2000
        assert cb.max_position_size == 5000

    def test_initial_state(self):
        cb = TradingCircuitBreaker()
        assert cb.is_tripped is False
        assert cb.trip_reason is None
        assert cb.trip_count == 0
        assert cb.daily_pnl == 0.0
        assert cb.minute_losses == []
        assert cb.minute_trades == []


class TestCheckTrade:
    """Test check_trade method."""

    def test_trade_allowed(self):
        cb = TradingCircuitBreaker()
        allowed, reason = cb.check_trade(5000)
        assert allowed is True
        assert reason == "OK"

    def test_trade_blocked_when_tripped(self):
        cb = TradingCircuitBreaker()
        cb.trip("manual trip")
        allowed, reason = cb.check_trade(100)
        assert allowed is False
        assert "Circuit breaker tripped" in reason

    def test_position_size_exceeded(self):
        cb = TradingCircuitBreaker(max_position_size=1000)
        allowed, reason = cb.check_trade(1500)
        assert allowed is False
        assert cb.is_tripped is True
        assert "Position size" in cb.trip_reason

    def test_negative_trade_value_checks_absolute(self):
        cb = TradingCircuitBreaker(max_position_size=1000)
        allowed, reason = cb.check_trade(-1500)
        assert allowed is False
        assert cb.is_tripped is True

    def test_position_size_at_limit_allowed(self):
        cb = TradingCircuitBreaker(max_position_size=1000)
        allowed, reason = cb.check_trade(1000)
        assert allowed is True
        assert reason == "OK"

    def test_trades_per_minute_exceeded(self):
        cb = TradingCircuitBreaker(max_trades_per_minute=3)
        cb.check_trade(100)
        cb.check_trade(100)
        cb.check_trade(100)
        allowed, reason = cb.check_trade(100)
        assert allowed is False
        assert cb.is_tripped is True
        assert "Too many trades" in cb.trip_reason

    def test_old_trades_expire_from_window(self):
        cb = TradingCircuitBreaker(max_trades_per_minute=2)
        # Add a trade timestamped 61 seconds ago
        cb.minute_trades.append(datetime.now() - timedelta(seconds=61))
        # This should be allowed since the old trade is outside the window
        allowed, reason = cb.check_trade(100)
        assert allowed is True

    def test_trade_recorded_on_success(self):
        cb = TradingCircuitBreaker()
        assert len(cb.minute_trades) == 0
        cb.check_trade(100)
        assert len(cb.minute_trades) == 1


class TestRecordPnl:
    """Test record_pnl method."""

    def test_positive_pnl(self):
        cb = TradingCircuitBreaker()
        cb.record_pnl(500)
        assert cb.daily_pnl == 500

    def test_negative_pnl_accumulates(self):
        cb = TradingCircuitBreaker()
        cb.record_pnl(-100)
        cb.record_pnl(-200)
        assert cb.daily_pnl == -300

    def test_daily_loss_trips_breaker(self):
        cb = TradingCircuitBreaker(max_daily_loss=500)
        cb.record_pnl(-600)
        assert cb.is_tripped is True
        assert "Daily loss" in cb.trip_reason

    def test_daily_loss_at_limit_no_trip(self):
        cb = TradingCircuitBreaker(max_daily_loss=500)
        cb.record_pnl(-500)
        assert cb.is_tripped is False

    def test_minute_loss_trips_breaker(self):
        cb = TradingCircuitBreaker(max_loss_per_minute=200, max_daily_loss=99999)
        # The minute loss check sums entries already in minute_losses before
        # appending the current one. So the third call sees -150 + -100 = -250
        # which exceeds the 200 limit.
        cb.record_pnl(-150)
        cb.record_pnl(-100)
        assert cb.is_tripped is False
        cb.record_pnl(-1)
        assert cb.is_tripped is True
        assert "Minute loss" in cb.trip_reason

    def test_pnl_recorded_in_minute_losses(self):
        cb = TradingCircuitBreaker()
        cb.record_pnl(-50)
        assert len(cb.minute_losses) == 1
        assert cb.minute_losses[0][1] == -50

    def test_daily_reset_on_new_day(self):
        cb = TradingCircuitBreaker()
        cb.record_pnl(-100)
        assert cb.daily_pnl == -100

        # Simulate last_reset being yesterday
        cb.last_reset = datetime.now() - timedelta(days=1)
        cb.record_pnl(-50)
        # daily_pnl should have been reset to 0 then -50 applied
        assert cb.daily_pnl == -50

    def test_old_minute_losses_pruned(self):
        cb = TradingCircuitBreaker()
        # Insert an old loss entry
        old_time = datetime.now() - timedelta(seconds=61)
        cb.minute_losses.append((old_time, -500))
        # Recording new pnl should prune the old entry
        cb.record_pnl(-10)
        # Only the new entry should remain
        assert len(cb.minute_losses) == 1


class TestTrip:
    """Test trip method."""

    def test_trip_sets_state(self):
        cb = TradingCircuitBreaker()
        cb.trip("test reason")
        assert cb.is_tripped is True
        assert cb.trip_reason == "test reason"
        assert cb.trip_count == 1

    def test_multiple_trips_increment_count(self):
        cb = TradingCircuitBreaker()
        cb.trip("first")
        cb.trip("second")
        cb.trip("third")
        assert cb.trip_count == 3
        assert cb.trip_reason == "third"


class TestReset:
    """Test reset method."""

    def test_reset_success(self):
        cb = TradingCircuitBreaker()
        cb.trip("test")
        result = cb.reset()
        assert result is True
        assert cb.is_tripped is False
        assert cb.trip_reason is None

    def test_reset_preserves_trip_count(self):
        cb = TradingCircuitBreaker()
        cb.trip("test")
        cb.reset()
        assert cb.trip_count == 1

    def test_reset_blocked_after_3_trips(self):
        cb = TradingCircuitBreaker()
        cb.trip("one")
        cb.trip("two")
        cb.trip("three")
        result = cb.reset()
        assert result is False
        assert cb.is_tripped is True

    def test_admin_override_after_3_trips(self):
        cb = TradingCircuitBreaker()
        cb.trip("one")
        cb.trip("two")
        cb.trip("three")
        result = cb.reset(admin_override=True)
        assert result is True
        assert cb.is_tripped is False

    def test_reset_without_trip(self):
        cb = TradingCircuitBreaker()
        result = cb.reset()
        assert result is True


class TestGetStatus:
    """Test get_status method."""

    def test_status_structure(self):
        cb = TradingCircuitBreaker()
        status = cb.get_status()
        assert "is_tripped" in status
        assert "trip_reason" in status
        assert "trip_count" in status
        assert "daily_pnl" in status
        assert "trades_last_minute" in status
        assert "loss_last_minute" in status
        assert "limits" in status
        assert "utilization" in status
        assert "last_reset" in status

    def test_status_initial_values(self):
        cb = TradingCircuitBreaker()
        status = cb.get_status()
        assert status["is_tripped"] is False
        assert status["trip_reason"] is None
        assert status["trip_count"] == 0
        assert status["daily_pnl"] == 0.0
        assert status["trades_last_minute"] == 0
        assert status["loss_last_minute"] == 0

    def test_status_limits_reflect_config(self):
        cb = TradingCircuitBreaker(
            max_loss_per_minute=100,
            max_trades_per_minute=5,
            max_daily_loss=1000,
            max_position_size=2000,
        )
        limits = cb.get_status()["limits"]
        assert limits["max_loss_per_minute"] == 100
        assert limits["max_trades_per_minute"] == 5
        assert limits["max_daily_loss"] == 1000
        assert limits["max_position_size"] == 2000

    def test_status_utilization_zero_when_positive_pnl(self):
        cb = TradingCircuitBreaker()
        cb.record_pnl(100)
        status = cb.get_status()
        assert status["utilization"]["daily_loss_pct"] == 0

    def test_status_utilization_reflects_activity(self):
        cb = TradingCircuitBreaker(max_trades_per_minute=10)
        cb.check_trade(100)
        cb.check_trade(100)
        status = cb.get_status()
        assert status["utilization"]["trades_pct"] == 20.0

    def test_status_after_trade(self):
        cb = TradingCircuitBreaker()
        cb.check_trade(100)
        status = cb.get_status()
        assert status["trades_last_minute"] == 1

    def test_status_last_reset_is_iso(self):
        cb = TradingCircuitBreaker()
        status = cb.get_status()
        # Should be parseable as ISO format
        datetime.fromisoformat(status["last_reset"])


class TestRepr:
    """Test __repr__ method."""

    def test_repr_active(self):
        cb = TradingCircuitBreaker()
        r = repr(cb)
        assert "ACTIVE" in r
        assert "trip_count=0" in r

    def test_repr_tripped(self):
        cb = TradingCircuitBreaker()
        cb.trip("test")
        r = repr(cb)
        assert "TRIPPED" in r
        assert "trip_count=1" in r
