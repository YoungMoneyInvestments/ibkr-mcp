"""
Trading circuit breaker system to prevent catastrophic losses.

Inspired by HedgeFundAI architecture - provides automatic trading halts
based on loss thresholds, trade velocity, and position size limits.
"""

import logging
from datetime import datetime
from typing import Tuple, List

from ..exceptions import CircuitBreakerError

logger = logging.getLogger(__name__)


class TradingCircuitBreaker:
    """
    Circuit breaker to prevent catastrophic losses.

    Monitors and enforces trading limits:
    - Maximum loss per minute
    - Maximum trades per minute
    - Maximum daily loss
    - Maximum position size

    When limits are exceeded, the breaker "trips" and prevents further trading
    until manually reset.
    """

    def __init__(
        self,
        max_loss_per_minute: float = 1000,
        max_trades_per_minute: int = 50,
        max_daily_loss: float = 5000,
        max_position_size: float = 10000
    ):
        """
        Initialize circuit breaker with safety limits.

        Args:
            max_loss_per_minute: Maximum allowed loss in a 60-second window
            max_trades_per_minute: Maximum number of trades in a 60-second window
            max_daily_loss: Maximum allowed loss for the trading day
            max_position_size: Maximum position value (dollars)
        """
        self.max_loss_per_minute = max_loss_per_minute
        self.max_trades_per_minute = max_trades_per_minute
        self.max_daily_loss = max_daily_loss
        self.max_position_size = max_position_size

        # Tracking variables
        self.minute_losses: List[Tuple[datetime, float]] = []
        self.minute_trades: List[datetime] = []
        self.daily_pnl = 0.0
        self.trip_count = 0
        self.is_tripped = False
        self.trip_reason = None
        self.last_reset = datetime.now()

        logger.info(
            f"Circuit breaker initialized - "
            f"max_loss_per_minute: ${max_loss_per_minute}, "
            f"max_trades_per_minute: {max_trades_per_minute}, "
            f"max_daily_loss: ${max_daily_loss}, "
            f"max_position_size: ${max_position_size}"
        )

    def check_trade(self, trade_value: float) -> Tuple[bool, str]:
        """
        Check if trade should be allowed.

        Args:
            trade_value: Dollar value of the proposed trade

        Returns:
            Tuple of (allowed: bool, reason: str)
            - If allowed: (True, "OK")
            - If blocked: (False, reason for blocking)
        """
        if self.is_tripped:
            return False, f"Circuit breaker tripped: {self.trip_reason}"

        current_time = datetime.now()

        # Check position size
        if abs(trade_value) > self.max_position_size:
            self.trip(
                f"Position size ${abs(trade_value):.2f} exceeds "
                f"limit ${self.max_position_size:.2f}"
            )
            return False, self.trip_reason

        # Check trades per minute
        self.minute_trades = [
            t for t in self.minute_trades
            if (current_time - t).total_seconds() < 60
        ]
        if len(self.minute_trades) >= self.max_trades_per_minute:
            self.trip(
                f"Too many trades: {len(self.minute_trades)} in last minute "
                f"(limit: {self.max_trades_per_minute})"
            )
            return False, self.trip_reason

        # Record this trade
        self.minute_trades.append(current_time)

        return True, "OK"

    def record_pnl(self, pnl: float):
        """
        Record profit/loss and check for breaker conditions.

        Args:
            pnl: Profit (positive) or loss (negative) amount

        Raises:
            CircuitBreakerError: If breaker trips due to losses
        """
        current_time = datetime.now()

        # Update daily P&L (reset on new day)
        if current_time.date() != self.last_reset.date():
            self.daily_pnl = 0
            self.last_reset = current_time
            logger.info("Circuit breaker daily P&L reset")

        self.daily_pnl += pnl

        # Check minute losses (rolling 60-second window)
        self.minute_losses = [
            (t, l) for t, l in self.minute_losses
            if (current_time - t).total_seconds() < 60
        ]
        minute_loss_total = sum(l for _, l in self.minute_losses if l < 0)

        # Check minute loss threshold
        if abs(minute_loss_total) > self.max_loss_per_minute:
            self.trip(
                f"Minute loss ${abs(minute_loss_total):.2f} exceeds "
                f"limit ${self.max_loss_per_minute:.2f}"
            )

        # Check daily loss threshold
        if self.daily_pnl < -self.max_daily_loss:
            self.trip(
                f"Daily loss ${abs(self.daily_pnl):.2f} exceeds "
                f"limit ${self.max_daily_loss:.2f}"
            )

        # Record this P&L event
        self.minute_losses.append((current_time, pnl))

    def trip(self, reason: str):
        """
        Trip the circuit breaker.

        Args:
            reason: Reason for tripping the breaker
        """
        self.is_tripped = True
        self.trip_reason = reason
        self.trip_count += 1
        logger.critical(f"CIRCUIT BREAKER TRIPPED: {reason}")
        logger.critical(
            f"Trip count: {self.trip_count}, "
            f"Daily P&L: ${self.daily_pnl:.2f}"
        )

    def reset(self, admin_override: bool = False) -> bool:
        """
        Reset the circuit breaker.

        Args:
            admin_override: Force reset even if trip count is high

        Returns:
            True if reset successful, False otherwise
        """
        if not admin_override and self.trip_count >= 3:
            logger.error(
                "Circuit breaker cannot be reset - too many trips "
                f"({self.trip_count}). Admin override required."
            )
            return False

        self.is_tripped = False
        self.trip_reason = None
        logger.info(
            f"Circuit breaker reset (trip count: {self.trip_count}, "
            f"admin_override: {admin_override})"
        )
        return True

    def get_status(self) -> dict:
        """
        Get current circuit breaker status.

        Returns:
            Dictionary with current state and metrics
        """
        current_time = datetime.now()

        # Calculate recent metrics
        recent_trades = [
            t for t in self.minute_trades
            if (current_time - t).total_seconds() < 60
        ]
        recent_losses = [
            (t, l) for t, l in self.minute_losses
            if (current_time - t).total_seconds() < 60
        ]
        recent_loss_total = sum(l for _, l in recent_losses if l < 0)

        return {
            "is_tripped": self.is_tripped,
            "trip_reason": self.trip_reason,
            "trip_count": self.trip_count,
            "daily_pnl": self.daily_pnl,
            "trades_last_minute": len(recent_trades),
            "loss_last_minute": abs(recent_loss_total),
            "limits": {
                "max_loss_per_minute": self.max_loss_per_minute,
                "max_trades_per_minute": self.max_trades_per_minute,
                "max_daily_loss": self.max_daily_loss,
                "max_position_size": self.max_position_size
            },
            "utilization": {
                "trades_pct": (len(recent_trades) / self.max_trades_per_minute) * 100,
                "loss_pct": (abs(recent_loss_total) / self.max_loss_per_minute) * 100,
                "daily_loss_pct": (abs(self.daily_pnl) / self.max_daily_loss) * 100
                                  if self.daily_pnl < 0 else 0
            },
            "last_reset": self.last_reset.isoformat()
        }

    def __repr__(self) -> str:
        """String representation of circuit breaker state."""
        status = "TRIPPED" if self.is_tripped else "ACTIVE"
        return (
            f"TradingCircuitBreaker(status={status}, "
            f"trip_count={self.trip_count}, "
            f"daily_pnl=${self.daily_pnl:.2f})"
        )
