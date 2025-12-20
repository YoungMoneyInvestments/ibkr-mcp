"""
Account and portfolio management tools for IBKR MCP.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from ib_async import Stock

from ..exceptions import DataError, MarketDataError
from ..models import Position, AccountSummary, PortfolioAllocation


async def get_account_summary(ib_client: Any) -> Dict[str, Any]:
    """
    Get account summary with balances and account values.

    Args:
        ib_client: Connected IB client instance (ib_async.IB)

    Returns:
        Dict with success, data (account summary), and timestamp
    """
    try:
        account_values = ib_client.accountValues()
        account_summary = ib_client.accountSummary()

        # Structure the response
        summary = {
            'account': account_summary[0].account if account_summary else None,
            'values': {},
        }

        # Group values by tag
        for av in account_values:
            if av.tag not in summary['values']:
                summary['values'][av.tag] = {}
            summary['values'][av.tag][av.currency] = float(av.value)

        return {
            'success': True,
            'data': summary,
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        return {
            'success': False,
            'data': None,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


async def get_positions(ib_client: Any) -> Dict[str, Any]:
    """
    Get current positions with P&L information.

    Args:
        ib_client: Connected IB client instance (ib_async.IB)

    Returns:
        Dict with success, data (list of positions), and timestamp
    """
    try:
        positions = ib_client.positions()

        # Convert positions to dictionaries
        position_list = []
        for pos in positions:
            position_list.append({
                'account': pos.account,
                'symbol': pos.contract.symbol,
                'sec_type': pos.contract.secType,
                'currency': pos.contract.currency,
                'position': float(pos.position),
                'avg_cost': float(pos.avgCost),
                'market_price': float(pos.marketPrice) if pos.marketPrice else None,
                'market_value': float(pos.marketValue) if pos.marketValue else None,
                'unrealized_pnl': float(pos.unrealizedPNL) if pos.unrealizedPNL else None,
                'realized_pnl': float(pos.realizedPNL) if pos.realizedPNL else None
            })

        return {
            'success': True,
            'data': position_list,
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        return {
            'success': False,
            'data': None,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


async def analyze_portfolio_allocation(ib_client: Any) -> Dict[str, Any]:
    """
    Analyze current portfolio allocation by asset class, symbol, and currency.

    Args:
        ib_client: Connected IB client instance (ib_async.IB)

    Returns:
        Dict with success, data (allocation analysis), and timestamp
    """
    try:
        # Get all positions
        positions = ib_client.positions()

        if not positions:
            return {
                'success': True,
                'data': {
                    "total_value": 0,
                    "allocations": {},
                    "message": "No positions found"
                },
                'timestamp': datetime.now().isoformat()
            }

        # Get account values
        account_values = ib_client.accountValues()
        total_value = 0
        for av in account_values:
            if av.tag == "NetLiquidation":
                total_value = float(av.value)
                break

        # Analyze allocations
        allocations = {
            "by_asset_class": {},
            "by_symbol": {},
            "by_sector": {},
            "by_currency": {}
        }

        for position in positions:
            contract = position.contract
            avg_cost = position.avgCost
            quantity = position.position

            # Get current market value
            ticker = ib_client.reqMktData(contract)
            await asyncio.sleep(0.5)  # Wait for data

            if ticker.marketPrice() and ticker.marketPrice() > 0:
                market_value = ticker.marketPrice() * quantity
            else:
                market_value = avg_cost * quantity

            ib_client.cancelMktData(contract)

            # By asset class
            asset_class = contract.secType
            if asset_class not in allocations["by_asset_class"]:
                allocations["by_asset_class"][asset_class] = {
                    "value": 0,
                    "percentage": 0,
                    "positions": []
                }
            allocations["by_asset_class"][asset_class]["value"] += market_value
            allocations["by_asset_class"][asset_class]["positions"].append(contract.symbol)

            # By symbol
            allocations["by_symbol"][contract.symbol] = {
                "quantity": quantity,
                "avg_cost": avg_cost,
                "market_value": market_value,
                "percentage": (market_value / total_value * 100) if total_value > 0 else 0,
                "pnl": market_value - (avg_cost * quantity)
            }

            # By currency
            currency = contract.currency
            if currency not in allocations["by_currency"]:
                allocations["by_currency"][currency] = {"value": 0, "percentage": 0}
            allocations["by_currency"][currency]["value"] += market_value

        # Calculate percentages
        if total_value > 0:
            for asset_class in allocations["by_asset_class"]:
                allocations["by_asset_class"][asset_class]["percentage"] = \
                    (allocations["by_asset_class"][asset_class]["value"] / total_value) * 100

            for currency in allocations["by_currency"]:
                allocations["by_currency"][currency]["percentage"] = \
                    (allocations["by_currency"][currency]["value"] / total_value) * 100

        return {
            'success': True,
            'data': {
                "total_value": total_value,
                "allocations": allocations,
                "position_count": len(positions)
            },
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        return {
            'success': False,
            'data': None,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


async def _get_current_price(ib_client: Any, symbol: str) -> float:
    """
    Helper to get current price for a symbol.

    Args:
        ib_client: Connected IB client instance
        symbol: Stock symbol

    Returns:
        Current price

    Raises:
        DataError: If price cannot be retrieved
    """
    contract = Stock(symbol, "SMART", "USD")
    ib_client.qualifyContracts(contract)

    ticker = ib_client.reqMktData(contract)
    await asyncio.sleep(0.5)

    price = ticker.marketPrice()
    ib_client.cancelMktData(contract)

    if price and price > 0:
        return price
    else:
        # Try to get from last trade
        trades = await ib_client.reqExecutionsAsync()
        for trade in trades:
            if trade.contract.symbol == symbol:
                return trade.execution.price
        raise DataError(f"Could not get price for {symbol}")


async def calculate_rebalancing_orders(
    ib_client: Any,
    target_allocations: Dict[str, float],
    rebalance_threshold: float = 0.05,
    use_cash: bool = True
) -> Dict[str, Any]:
    """
    Calculate orders needed to rebalance portfolio to target allocations.

    Args:
        ib_client: Connected IB client instance
        target_allocations: Dict of symbol -> target percentage (0-100)
        rebalance_threshold: Only rebalance if deviation > threshold (default 5%)
        use_cash: Whether to use available cash for rebalancing

    Returns:
        Dict with success, data (list of required trades), and timestamp
    """
    try:
        # Get current portfolio analysis
        portfolio_result = await analyze_portfolio_allocation(ib_client)

        if not portfolio_result['success']:
            return {
                'success': False,
                'data': None,
                'error': portfolio_result.get('error', 'Failed to analyze portfolio'),
                'timestamp': datetime.now().isoformat()
            }

        portfolio = portfolio_result['data']

        if portfolio["total_value"] == 0:
            return {
                'success': False,
                'data': None,
                'error': "No portfolio value to rebalance",
                'timestamp': datetime.now().isoformat()
            }

        total_value = portfolio["total_value"]
        current_allocations = portfolio["allocations"]["by_symbol"]

        # Get available cash if using it
        available_cash = 0
        if use_cash:
            account_values = ib_client.accountValues()
            for av in account_values:
                if av.tag == "AvailableFunds":
                    available_cash = float(av.value)
                    break

        rebalancing_value = total_value + available_cash

        # Calculate required trades
        trades = []
        total_buy_value = 0
        total_sell_value = 0

        # Check all target symbols
        for symbol, target_pct in target_allocations.items():
            target_value = rebalancing_value * (target_pct / 100)
            current_value = current_allocations.get(symbol, {}).get("market_value", 0)
            current_pct = (current_value / rebalancing_value * 100) if rebalancing_value > 0 else 0

            deviation = abs(target_pct - current_pct)

            # Only rebalance if deviation exceeds threshold
            if deviation > rebalance_threshold:
                value_diff = target_value - current_value

                if value_diff > 0:
                    # Need to buy
                    action = "BUY"
                    quantity = int(abs(value_diff) / await _get_current_price(ib_client, symbol))
                    total_buy_value += abs(value_diff)
                else:
                    # Need to sell
                    action = "SELL"
                    quantity = int(abs(value_diff) / await _get_current_price(ib_client, symbol))
                    total_sell_value += abs(value_diff)

                if quantity > 0:
                    trades.append({
                        "symbol": symbol,
                        "action": action,
                        "quantity": quantity,
                        "current_pct": round(current_pct, 2),
                        "target_pct": target_pct,
                        "deviation": round(deviation, 2),
                        "value_change": round(value_diff, 2)
                    })

        # Check for positions to exit (not in target allocations)
        for symbol, position in current_allocations.items():
            if symbol not in target_allocations and position["market_value"] > 0:
                trades.append({
                    "symbol": symbol,
                    "action": "SELL",
                    "quantity": abs(int(position["quantity"])),
                    "current_pct": round(position["percentage"], 2),
                    "target_pct": 0,
                    "deviation": round(position["percentage"], 2),
                    "value_change": -position["market_value"]
                })
                total_sell_value += position["market_value"]

        return {
            'success': True,
            'data': {
                "trades_required": trades,
                "total_buy_value": round(total_buy_value, 2),
                "total_sell_value": round(total_sell_value, 2),
                "net_cash_needed": round(total_buy_value - total_sell_value, 2),
                "available_cash": round(available_cash, 2),
                "feasible": (total_buy_value - total_sell_value) <= available_cash
            },
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        return {
            'success': False,
            'data': None,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


async def execute_rebalancing(
    ib_client: Any,
    rebalancing_plan: Dict[str, Any],
    place_order_func: Any,
    order_type: str = "MARKET",
    execute_sells_first: bool = True
) -> Dict[str, Any]:
    """
    Execute the rebalancing trades from a rebalancing plan.

    Args:
        ib_client: Connected IB client instance
        rebalancing_plan: Output from calculate_rebalancing_orders
        place_order_func: Function to place orders (async callable)
        order_type: MARKET or LIMIT
        execute_sells_first: Execute sells before buys to raise cash

    Returns:
        Dict with success, data (list of trade results), and timestamp
    """
    try:
        # Validate the rebalancing plan
        if not rebalancing_plan.get("success"):
            return {
                'success': False,
                'data': None,
                'error': "Invalid rebalancing plan",
                'timestamp': datetime.now().isoformat()
            }

        plan_data = rebalancing_plan.get("data", {})

        if not plan_data.get("feasible") and not execute_sells_first:
            return {
                'success': False,
                'data': None,
                'error': "Insufficient cash for rebalancing",
                'timestamp': datetime.now().isoformat()
            }

        trades = plan_data.get("trades_required", [])
        results = []

        # Separate buys and sells
        sells = [t for t in trades if t["action"] == "SELL"]
        buys = [t for t in trades if t["action"] == "BUY"]

        # Execute sells first if requested
        if execute_sells_first:
            for trade in sells:
                try:
                    result = await place_order_func(
                        symbol=trade["symbol"],
                        action=trade["action"],
                        quantity=trade["quantity"],
                        order_type=order_type
                    )
                    results.append({
                        "symbol": trade["symbol"],
                        "action": trade["action"],
                        "quantity": trade["quantity"],
                        "status": "submitted",
                        "order_id": result.get("order_id")
                    })
                except Exception as e:
                    results.append({
                        "symbol": trade["symbol"],
                        "action": trade["action"],
                        "quantity": trade["quantity"],
                        "status": "failed",
                        "error": str(e)
                    })

            # Wait for sells to complete if needed
            if sells:
                await asyncio.sleep(2)

        # Execute buys
        for trade in buys:
            try:
                result = await place_order_func(
                    symbol=trade["symbol"],
                    action=trade["action"],
                    quantity=trade["quantity"],
                    order_type=order_type
                )
                results.append({
                    "symbol": trade["symbol"],
                    "action": trade["action"],
                    "quantity": trade["quantity"],
                    "status": "submitted",
                    "order_id": result.get("order_id")
                })
            except Exception as e:
                results.append({
                    "symbol": trade["symbol"],
                    "action": trade["action"],
                    "quantity": trade["quantity"],
                    "status": "failed",
                    "error": str(e)
                })

        # Execute remaining sells if not done first
        if not execute_sells_first:
            for trade in sells:
                try:
                    result = await place_order_func(
                        symbol=trade["symbol"],
                        action=trade["action"],
                        quantity=trade["quantity"],
                        order_type=order_type
                    )
                    results.append({
                        "symbol": trade["symbol"],
                        "action": trade["action"],
                        "quantity": trade["quantity"],
                        "status": "submitted",
                        "order_id": result.get("order_id")
                    })
                except Exception as e:
                    results.append({
                        "symbol": trade["symbol"],
                        "action": trade["action"],
                        "quantity": trade["quantity"],
                        "status": "failed",
                        "error": str(e)
                    })

        # Count successes and failures
        successful = sum(1 for r in results if r["status"] == "submitted")
        failed = sum(1 for r in results if r["status"] == "failed")

        return {
            'success': True,
            'data': {
                "results": results,
                "summary": {
                    "total_trades": len(results),
                    "successful": successful,
                    "failed": failed
                }
            },
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        return {
            'success': False,
            'data': None,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }
