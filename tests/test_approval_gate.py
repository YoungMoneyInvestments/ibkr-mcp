"""Tests for the approval-required-by-default execution gate.

Verifies that order-placement tools do NOT transmit to IBKR unless either
(a) confirm=True is passed, or (b) IBKR_MCP_AUTONOMOUS_EXECUTION is enabled
on the client config. This is the default posture for the live-trading
execution path; see IBKRConfig.autonomous_execution.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ibkr_mcp.config import IBKRConfig
from ibkr_mcp.tools import orders


def make_mock_client(autonomous_execution: bool = False) -> MagicMock:
    """Build a mock IBKRClient sufficient to drive tools.orders.place_order."""
    client = MagicMock()
    client.config = IBKRConfig(autonomous_execution=autonomous_execution)
    client.is_connected.return_value = True
    client.connect = AsyncMock()
    client.rate_limit = AsyncMock()

    qualified_contract = MagicMock()
    client.ib.qualifyContracts.return_value = [qualified_contract]

    fake_trade = MagicMock()
    fake_trade.order.orderId = 42
    fake_trade.contract.symbol = "AAPL"
    fake_trade.order.action = "BUY"
    fake_trade.order.totalQuantity = 10
    fake_trade.order.orderType = "MKT"
    fake_trade.order.lmtPrice = 0
    fake_trade.order.auxPrice = 0
    fake_trade.orderStatus.status = "Submitted"
    fake_trade.orderStatus.filled = 0
    fake_trade.orderStatus.remaining = 10
    fake_trade.orderStatus.avgFillPrice = 0
    fake_trade.orderStatus.lastFillTime = ""
    fake_trade.commission = None
    client.ib.placeOrder.return_value = fake_trade

    return client


class TestApprovalRequiredByDefault:
    """Default posture: approval required, nothing transmits without confirm."""

    @pytest.mark.asyncio
    async def test_default_config_stages_order_without_transmitting(self):
        """With no confirm and autonomous_execution unset, order must NOT transmit."""
        client = make_mock_client(autonomous_execution=False)

        result = await orders.place_order(
            client,
            symbol="AAPL",
            action="BUY",
            quantity=10,
            order_type="MKT",
        )

        # The real chokepoint must never be reached.
        client.ib.placeOrder.assert_not_called()

        # A structured pending-approval response describing the would-be order.
        assert result["success"] is True
        assert result["status"] == "PENDING_APPROVAL"
        assert result["pending_approval"] is True
        assert result["would_place"]["symbol"] == "AAPL"
        assert result["would_place"]["action"] == "BUY"
        assert result["would_place"]["quantity"] == 10
        assert result["would_place"]["order_type"] == "MKT"

    @pytest.mark.asyncio
    async def test_confirm_false_explicit_still_stages(self):
        """Explicit confirm=False behaves the same as omitting it."""
        client = make_mock_client(autonomous_execution=False)

        result = await orders.place_order(
            client, symbol="MSFT", action="SELL", quantity=5, confirm=False
        )

        client.ib.placeOrder.assert_not_called()
        assert result["pending_approval"] is True


class TestConfirmTrueTransmits:
    """confirm=True is the explicit approval step that actually transmits."""

    @pytest.mark.asyncio
    async def test_confirm_true_reaches_transmit_path(self):
        client = make_mock_client(autonomous_execution=False)

        result = await orders.place_order(
            client, symbol="AAPL", action="BUY", quantity=10, confirm=True
        )

        client.ib.placeOrder.assert_called_once()
        assert result["success"] is True
        assert result["order_id"] == 42
        assert "pending_approval" not in result


class TestAutonomousExecutionOptIn:
    """IBKR_MCP_AUTONOMOUS_EXECUTION opt-in restores today's immediate-transmit behavior."""

    def test_env_var_disabled_by_default(self):
        """Autonomous execution must default to False when unset."""
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=True):
            config = IBKRConfig.from_env()
        assert config.autonomous_execution is False

    def test_env_var_enables_autonomous_execution(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"IBKR_MCP_AUTONOMOUS_EXECUTION": "true"}, clear=True):
            config = IBKRConfig.from_env()
        assert config.autonomous_execution is True

    @pytest.mark.asyncio
    async def test_autonomous_mode_transmits_without_confirm(self):
        """With autonomous_execution enabled, no confirm=True is needed to transmit."""
        client = make_mock_client(autonomous_execution=True)

        result = await orders.place_order(
            client, symbol="AAPL", action="BUY", quantity=10
        )

        client.ib.placeOrder.assert_called_once()
        assert result["success"] is True
        assert result["order_id"] == 42
        assert "pending_approval" not in result
