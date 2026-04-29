"""Regression tests for heartbeat and reconnect behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ibkr_mcp.client import IBKRClient
from ibkr_mcp.config import IBKRConfig


@pytest.fixture
def client() -> IBKRClient:
    """Create a client with mock IB connection for heartbeat tests."""
    instance = IBKRClient(IBKRConfig())
    instance.ib = MagicMock()
    instance._connected = True
    return instance


@pytest.mark.asyncio
async def test_heartbeat_uses_async_time_request(client: IBKRClient) -> None:
    """Heartbeat should use async request path and avoid sync call."""
    client.ib.reqCurrentTimeAsync = AsyncMock(
        return_value="2026-04-29T06:24:22Z"
    )
    client.ib.reqCurrentTime = MagicMock(
        side_effect=RuntimeError("sync path should not be used")
    )
    client.ib.isConnected.return_value = True

    with patch(
        "ibkr_mcp.client.asyncio.sleep",
        AsyncMock(side_effect=[None, asyncio.CancelledError()]),
    ):
        await client._heartbeat_loop()

    client.ib.reqCurrentTimeAsync.assert_awaited_once()
    client.ib.reqCurrentTime.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_runtime_loop_error_skips_reconnect_when_connected(
    client: IBKRClient,
) -> None:
    """Event-loop reentrancy errors should not trigger reconnect if still connected."""
    client.ib.reqCurrentTimeAsync = AsyncMock(
        side_effect=RuntimeError("This event loop is already running")
    )
    client.ib.isConnected.return_value = True
    client._schedule_reconnect = MagicMock()

    with patch(
        "ibkr_mcp.client.asyncio.sleep",
        AsyncMock(side_effect=[None, asyncio.CancelledError()]),
    ):
        await client._heartbeat_loop()

    client._schedule_reconnect.assert_not_called()
    assert client._last_heartbeat > 0


@pytest.mark.asyncio
async def test_schedule_reconnect_ignores_duplicate_trigger(
    client: IBKRClient,
) -> None:
    """A running reconnect task should suppress duplicate scheduling."""
    existing_task = asyncio.create_task(asyncio.sleep(60))
    client._reconnect_task = existing_task

    try:
        with patch("ibkr_mcp.client.asyncio.create_task") as mock_create_task:
            client._schedule_reconnect("heartbeat")
            mock_create_task.assert_not_called()
    finally:
        existing_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await existing_task
