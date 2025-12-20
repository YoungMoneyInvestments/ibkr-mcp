"""
Basic order management tools for IBKR MCP Server.

Provides fundamental order placement and management capabilities:
- Market, limit, and stop orders
- Order cancellation
- Open orders retrieval
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ib_async import MarketOrder, LimitOrder, StopOrder, Stock, Option, Future, Forex

from ..client import IBKRClient
from ..models import OrderAction, OrderType, SecType
from ..exceptions import OrderError, ValidationError

logger = logging.getLogger(__name__)


# =============================================================================
# Order Placement
# =============================================================================


async def place_order(
    client: IBKRClient,
    symbol: str,
    action: str,
    quantity: int,
    order_type: str = "MKT",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    sec_type: str = "STK",
    exchange: str = "SMART",
) -> Dict[str, Any]:
    """
    Place a basic order (market, limit, or stop).

    Args:
        client: IBKR client instance
        symbol: Symbol to trade
        action: Order action (BUY/SELL)
        quantity: Number of shares/contracts
        order_type: Order type (MKT, LMT, STP)
        limit_price: Limit price for limit orders
        stop_price: Stop price for stop orders
        sec_type: Security type (STK, OPT, FUT, CASH)
        exchange: Exchange to route order (default SMART)

    Returns:
        Dict containing order details and status

    Raises:
        OrderError: If order placement fails
        ValidationError: If parameters are invalid
    """
    try:
        # Validate inputs
        if quantity <= 0:
            raise ValidationError("Quantity must be positive")

        action = action.upper()
        if action not in ["BUY", "SELL"]:
            raise ValidationError(f"Invalid action: {action}. Must be BUY or SELL")

        order_type = order_type.upper()

        # Ensure client is connected
        if not client.is_connected():
            await client.connect()

        # Apply rate limiting
        await client.rate_limit()

        # Create contract
        contract = _create_contract(client, symbol, sec_type, exchange)

        # Create order based on type
        if order_type == "MKT":
            order = MarketOrder(action, quantity)
        elif order_type == "LMT":
            if limit_price is None:
                raise ValidationError("Limit price required for limit orders")
            order = LimitOrder(action, quantity, limit_price)
        elif order_type == "STP":
            if stop_price is None:
                raise ValidationError("Stop price required for stop orders")
            order = StopOrder(action, quantity, stop_price)
        else:
            raise ValidationError(f"Unsupported order type: {order_type}")

        # Place the order
        trade = client.ib.placeOrder(contract, order)

        # Wait for order to be acknowledged
        await asyncio.sleep(1)

        # Convert to dict
        result = _trade_to_dict(trade)
        result["timestamp"] = datetime.now().isoformat()
        result["success"] = True

        logger.info(
            f"Order placed: {symbol} {action} {quantity} @ {order_type}, "
            f"order_id={trade.order.orderId}"
        )

        return result

    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error placing order for {symbol}: {e}")
        raise OrderError(f"Failed to place order: {e}")


# =============================================================================
# Order Management
# =============================================================================


async def cancel_order(client: IBKRClient, order_id: int) -> Dict[str, Any]:
    """
    Cancel an open order.

    Args:
        client: IBKR client instance
        order_id: Order ID to cancel

    Returns:
        Dict with cancellation status

    Raises:
        OrderError: If cancellation fails
    """
    try:
        # Ensure client is connected
        if not client.is_connected():
            await client.connect()

        # Find the order
        found = False
        for trade in client.ib.openTrades():
            if trade.order.orderId == order_id:
                client.ib.cancelOrder(trade.order)
                await asyncio.sleep(1)  # Wait for cancellation
                found = True
                logger.info(f"Order {order_id} cancelled")
                break

        if not found:
            logger.warning(
                f"Order {order_id} not found (may already be filled or cancelled)"
            )

        return {
            "success": found,
            "order_id": order_id,
            "message": "Order cancelled" if found else "Order not found",
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error canceling order {order_id}: {e}")
        raise OrderError(f"Failed to cancel order: {e}")


async def get_open_orders(client: IBKRClient) -> Dict[str, Any]:
    """
    Get all open orders.

    Args:
        client: IBKR client instance

    Returns:
        Dict containing list of open orders

    Raises:
        OrderError: If retrieval fails
    """
    try:
        # Ensure client is connected
        if not client.is_connected():
            await client.connect()

        trades = client.ib.openTrades()
        orders = [_trade_to_dict(trade) for trade in trades]

        logger.info(f"Retrieved {len(orders)} open orders")

        return {
            "success": True,
            "data": orders,
            "count": len(orders),
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error getting open orders: {e}")
        raise OrderError(f"Failed to get open orders: {e}")


# =============================================================================
# Helper Functions
# =============================================================================


def _create_contract(client: IBKRClient, symbol: str, sec_type: str, exchange: str):
    """
    Create and qualify a contract.

    Args:
        client: IBKR client instance
        symbol: Symbol to trade
        sec_type: Security type (STK, OPT, FUT, CASH)
        exchange: Exchange

    Returns:
        Qualified contract

    Raises:
        ValidationError: If contract cannot be created or qualified
    """
    sec_type = sec_type.upper()

    try:
        if sec_type == "STK":
            contract = Stock(symbol, exchange, "USD")
        elif sec_type == "OPT":
            # For options, symbol should be in format: "SYMBOL YYMMDD C/P STRIKE"
            parts = symbol.split()
            if len(parts) < 4:
                raise ValidationError(
                    "Option symbol format: SYMBOL YYMMDD C/P STRIKE"
                )
            contract = Option(parts[0], parts[1], parts[3], parts[2], exchange, "USD")
        elif sec_type == "FUT":
            contract = Future(symbol, exchange=exchange)
        elif sec_type == "CASH":
            contract = Forex(symbol)
        else:
            raise ValidationError(f"Unsupported security type: {sec_type}")

        # Qualify the contract
        qualified = client.ib.qualifyContracts(contract)
        if not qualified:
            raise ValidationError(f"Failed to qualify contract for {symbol}")

        return qualified[0] if isinstance(qualified, list) else qualified

    except ValidationError:
        raise
    except Exception as e:
        raise ValidationError(f"Contract creation failed: {e}")


def _trade_to_dict(trade) -> Dict[str, Any]:
    """
    Convert trade object to dictionary.

    Args:
        trade: IB trade object

    Returns:
        Dict with trade details
    """
    return {
        "order_id": trade.order.orderId,
        "symbol": trade.contract.symbol,
        "action": trade.order.action,
        "quantity": trade.order.totalQuantity,
        "order_type": trade.order.orderType,
        "limit_price": (
            float(trade.order.lmtPrice) if trade.order.lmtPrice else None
        ),
        "stop_price": (
            float(trade.order.auxPrice) if trade.order.auxPrice else None
        ),
        "status": trade.orderStatus.status,
        "filled": trade.orderStatus.filled,
        "remaining": trade.orderStatus.remaining,
        "avg_fill_price": (
            float(trade.orderStatus.avgFillPrice)
            if trade.orderStatus.avgFillPrice
            else None
        ),
        "last_fill_time": trade.orderStatus.lastFillTime,
        "commission": float(trade.commission) if trade.commission else None,
    }
