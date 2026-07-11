"""Tests for the approval-required-by-default gate on composite/batch tools.

execute_rebalancing (tools/account.py) and set_stop_loss_orders (tools/risk.py)
are higher-level tools that place multiple orders under the hood via the same
order-transmit chokepoints covered by test_approval_gate.py. This verifies the
gap closed on top of that work: confirm is threaded through the whole batch,
so without confirm=True (and without autonomous_execution) NOT A SINGLE order
in the batch reaches client.ib.placeOrder, and with confirm=True every order
in the batch does.
"""

import functools

from unittest.mock import AsyncMock, MagicMock

import pytest

from ibkr_mcp.config import IBKRConfig
from ibkr_mcp.tools import account, orders, orders_advanced, risk


def make_mock_order_client(autonomous_execution: bool = False) -> MagicMock:
    """Mock client sufficient to drive the real tools.orders.place_order gate."""
    client = MagicMock()
    client.config = IBKRConfig(autonomous_execution=autonomous_execution)
    client.is_connected.return_value = True
    client.connect = AsyncMock()
    client.rate_limit = AsyncMock()

    client.ib.qualifyContracts.return_value = [MagicMock()]

    fake_trade = MagicMock()
    fake_trade.order.orderId = 101
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


def make_mock_stop_loss_client(autonomous_execution: bool = False) -> MagicMock:
    """Mock client sufficient to drive the real tools.orders_advanced.place_trailing_stop gate."""
    client = MagicMock()
    client.config = IBKRConfig(autonomous_execution=autonomous_execution)
    client.is_connected.return_value = True
    client.connect = AsyncMock()
    client.rate_limit = AsyncMock()

    client.ib.qualifyContracts.return_value = [MagicMock()]

    position_1 = MagicMock()
    position_1.position = 100
    position_1.contract = MagicMock(symbol="AAPL", secType="STK", exchange="SMART")

    position_2 = MagicMock()
    position_2.position = -50
    position_2.contract = MagicMock(symbol="MSFT", secType="STK", exchange="SMART")

    client.ib.positions.return_value = [position_1, position_2]

    ticker = MagicMock()
    ticker.marketPrice.return_value = 150.0
    client.ib.reqMktData.return_value = ticker
    client.ib.cancelMktData = MagicMock()

    fake_trade = MagicMock()
    fake_trade.order.orderId = 202
    fake_trade.orderStatus.status = "Submitted"
    client.ib.placeOrder.return_value = fake_trade

    # risk.set_stop_loss_orders calls client.place_trailing_stop(...) directly,
    # so bind the real tool function to this mock client (same pattern as
    # IBKRClient.place_trailing_stop delegating to orders_advanced).
    client.place_trailing_stop = functools.partial(
        orders_advanced.place_trailing_stop, client
    )

    return client


def make_rebalancing_plan() -> dict:
    return {
        "success": True,
        "data": {
            "feasible": True,
            "trades_required": [
                {"symbol": "AAPL", "action": "SELL", "quantity": 10},
                {"symbol": "MSFT", "action": "BUY", "quantity": 5},
            ],
        },
    }


# NOTE: tools.orders.place_order only accepts MKT/LMT/STP order types, while
# execute_rebalancing's own default order_type is "MARKET" -- a pre-existing
# mismatch unrelated to the approval gate. Tests pass order_type="MKT"
# explicitly so the underlying order construction succeeds and the approval
# gate itself is what's under test.


class TestExecuteRebalancingApprovalGate:
    """execute_rebalancing must never transmit part of a batch without confirm."""

    @pytest.mark.asyncio
    async def test_default_no_confirm_stages_whole_batch_without_transmitting(self):
        client = make_mock_order_client(autonomous_execution=False)

        async def place_order_func(**kwargs):
            return await orders.place_order(client, **kwargs)

        result = await account.execute_rebalancing(
            client,
            make_rebalancing_plan(),
            place_order_func,
            order_type="MKT",
        )

        # Not one order in the batch reaches the real transmit chokepoint.
        client.ib.placeOrder.assert_not_called()

        assert result["success"] is True
        assert result["status"] == "PENDING_APPROVAL"
        assert result["pending_approval"] is True

        batch_results = result["data"]["results"]
        assert len(batch_results) == 2
        for entry in batch_results:
            assert entry["status"] == "PENDING_APPROVAL"
            assert entry["would_place"]["symbol"] in {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_confirm_true_transmits_every_order_in_batch(self):
        client = make_mock_order_client(autonomous_execution=False)

        async def place_order_func(**kwargs):
            return await orders.place_order(client, **kwargs)

        result = await account.execute_rebalancing(
            client,
            make_rebalancing_plan(),
            place_order_func,
            order_type="MKT",
            confirm=True,
        )

        assert client.ib.placeOrder.call_count == 2
        assert "pending_approval" not in result
        assert "status" not in result

        batch_results = result["data"]["results"]
        assert len(batch_results) == 2
        for entry in batch_results:
            assert entry["status"] == "submitted"
            assert entry["order_id"] == 101

    @pytest.mark.asyncio
    async def test_autonomous_execution_transmits_without_confirm(self):
        client = make_mock_order_client(autonomous_execution=True)

        async def place_order_func(**kwargs):
            return await orders.place_order(client, **kwargs)

        result = await account.execute_rebalancing(
            client,
            make_rebalancing_plan(),
            place_order_func,
            order_type="MKT",
        )

        assert client.ib.placeOrder.call_count == 2
        assert "pending_approval" not in result


class TestSetStopLossOrdersApprovalGate:
    """set_stop_loss_orders must never transmit part of a batch without confirm."""

    @pytest.mark.asyncio
    async def test_default_no_confirm_stages_whole_batch_without_transmitting(self):
        client = make_mock_stop_loss_client(autonomous_execution=False)

        result = await risk.set_stop_loss_orders(client)

        # Not one trailing stop in the batch reaches the real transmit chokepoint.
        client.ib.placeOrder.assert_not_called()

        assert result["success"] is True
        assert result["status"] == "PENDING_APPROVAL"
        assert result["pending_approval"] is True

        orders_placed = result["orders_placed"]
        assert len(orders_placed) == 2
        for entry in orders_placed:
            assert entry["status"] == "PENDING_APPROVAL"
            assert entry["would_place"]["order_type"] == "TRAILING_STOP"

    @pytest.mark.asyncio
    async def test_confirm_true_transmits_every_stop_in_batch(self):
        client = make_mock_stop_loss_client(autonomous_execution=False)

        result = await risk.set_stop_loss_orders(client, confirm=True)

        assert client.ib.placeOrder.call_count == 2
        assert "pending_approval" not in result

        orders_placed = result["orders_placed"]
        assert len(orders_placed) == 2
        for entry in orders_placed:
            assert entry["order_id"] == 202

    @pytest.mark.asyncio
    async def test_autonomous_execution_transmits_without_confirm(self):
        client = make_mock_stop_loss_client(autonomous_execution=True)

        result = await risk.set_stop_loss_orders(client)

        assert client.ib.placeOrder.call_count == 2
        assert "pending_approval" not in result
