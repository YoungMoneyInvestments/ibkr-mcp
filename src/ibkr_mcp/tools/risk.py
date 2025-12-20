"""
Risk management tools for IBKR MCP Server.

Provides position sizing, risk limit checking, stop loss management,
and Value at Risk (VaR) calculations.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
from scipy import stats
from ib_async import Stock

from ..exceptions import DataError, ValidationError

logger = logging.getLogger(__name__)


async def calculate_position_size(
    client: Any,
    symbol: str,
    risk_amount: float,
    stop_loss: float,
    entry_price: Optional[float] = None,
    method: str = "fixed_risk"
) -> Dict[str, Any]:
    """
    Calculate optimal position size based on risk parameters.

    Args:
        client: IBKRClient instance
        symbol: Trading symbol
        risk_amount: Dollar amount to risk
        stop_loss: Stop loss price
        entry_price: Entry price (current price if None)
        method: Sizing method (fixed_risk, kelly, volatility_based)

    Returns:
        Dictionary containing:
            - success: Boolean status
            - symbol: Trading symbol
            - method: Sizing method used
            - position_size: Calculated position size (shares)
            - entry_price: Entry price used
            - stop_loss: Stop loss price
            - risk_amount: Risk amount
            - total_value: Total position value
            - risk_per_share: Risk per share
            - risk_percentage: Risk as percentage of entry
            - timestamp: Calculation timestamp
    """
    try:
        # Get current price if not provided
        if not entry_price:
            contract = Stock(symbol, "SMART", "USD")
            client.ib.qualifyContracts(contract)
            ticker = client.ib.reqMktData(contract)
            await asyncio.sleep(0.5)
            entry_price = ticker.marketPrice()
            client.ib.cancelMktData(contract)

        if method == "fixed_risk":
            # Simple fixed risk calculation
            risk_per_share = abs(entry_price - stop_loss)
            if risk_per_share == 0:
                return {
                    "success": False,
                    "error": "Invalid stop loss - results in zero risk per share",
                    "timestamp": datetime.now().isoformat()
                }

            position_size = int(risk_amount / risk_per_share)
            total_value = position_size * entry_price

        elif method == "kelly":
            # Kelly Criterion (simplified version)
            kelly_fraction = 0.25  # Conservative Kelly
            account_values = client.ib.accountValues()
            account_value = 0
            for av in account_values:
                if av.tag == "NetLiquidation":
                    account_value = float(av.value)
                    break

            position_value = account_value * kelly_fraction
            position_size = int(position_value / entry_price)
            total_value = position_size * entry_price

        elif method == "volatility_based":
            # Size based on volatility
            # Get historical data (assuming client has get_historical_data method)
            if hasattr(client, 'get_historical_data'):
                hist_data = await client.get_historical_data(
                    symbol=symbol,
                    duration="30 D",
                    bar_size="1 day"
                )

                if hist_data.get("status") == "success" and hist_data.get("data"):
                    prices = [bar["close"] for bar in hist_data["data"]]
                    returns = [
                        (prices[i] - prices[i-1]) / prices[i-1]
                        for i in range(1, len(prices))
                    ]
                    volatility = np.std(returns) if returns else 0.02

                    # Position inversely proportional to volatility
                    volatility_multiplier = 0.02 / max(volatility, 0.01)
                    base_size = risk_amount / entry_price
                    position_size = int(base_size * volatility_multiplier)
                    total_value = position_size * entry_price
                else:
                    return {
                        "success": False,
                        "error": "Could not calculate volatility",
                        "timestamp": datetime.now().isoformat()
                    }
            else:
                return {
                    "success": False,
                    "error": "Volatility-based sizing requires historical data support",
                    "timestamp": datetime.now().isoformat()
                }

        else:
            return {
                "success": False,
                "error": f"Unknown method: {method}",
                "timestamp": datetime.now().isoformat()
            }

        return {
            "success": True,
            "symbol": symbol,
            "method": method,
            "position_size": position_size,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "risk_amount": risk_amount,
            "total_value": total_value,
            "risk_per_share": abs(entry_price - stop_loss),
            "risk_percentage": (abs(entry_price - stop_loss) / entry_price) * 100,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Position sizing failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def check_risk_limits(client: Any) -> Dict[str, Any]:
    """
    Check current portfolio against risk limits.

    Args:
        client: IBKRClient instance

    Returns:
        Dictionary containing:
            - success: Boolean status
            - overall_risk_status: OK, WARNING, or CRITICAL
            - net_liquidation: Account net liquidation value
            - risk_checks: Dictionary of individual risk checks
            - position_count: Number of positions
            - largest_position: Details of largest position
            - timestamp: Check timestamp
    """
    try:
        # Get account values
        account_values = client.ib.accountValues()
        account_data = {}
        for av in account_values:
            account_data[av.tag] = float(av.value) if av.value else 0

        net_liquidation = account_data.get("NetLiquidation", 0)
        buying_power = account_data.get("BuyingPower", 0)
        margin_used = account_data.get("MaintMarginReq", 0)
        excess_liquidity = account_data.get("ExcessLiquidity", 0)

        # Calculate risk metrics
        margin_utilization = (
            (margin_used / net_liquidation * 100)
            if net_liquidation > 0 else 0
        )

        # Get positions for concentration risk
        positions = client.ib.positions()
        position_values = {}
        largest_position = 0

        for position in positions:
            contract = position.contract
            value = abs(position.position * position.avgCost)
            position_values[contract.symbol] = value
            largest_position = max(largest_position, value)

        concentration_risk = (
            (largest_position / net_liquidation * 100)
            if net_liquidation > 0 else 0
        )

        # Define risk limits
        risk_checks = {
            "margin_utilization": {
                "current": margin_utilization,
                "limit": 50,  # 50% margin utilization limit
                "status": (
                    "OK" if margin_utilization < 50
                    else "WARNING" if margin_utilization < 70
                    else "CRITICAL"
                )
            },
            "concentration_risk": {
                "current": concentration_risk,
                "limit": 20,  # 20% max position size
                "status": (
                    "OK" if concentration_risk < 20
                    else "WARNING" if concentration_risk < 30
                    else "CRITICAL"
                )
            },
            "buying_power": {
                "current": buying_power,
                "minimum": net_liquidation * 0.1,  # Keep 10% in reserve
                "status": "OK" if buying_power > net_liquidation * 0.1 else "WARNING"
            },
            "excess_liquidity": {
                "current": excess_liquidity,
                "minimum": net_liquidation * 0.05,  # 5% minimum excess
                "status": "OK" if excess_liquidity > net_liquidation * 0.05 else "WARNING"
            }
        }

        # Overall risk status
        statuses = [check["status"] for check in risk_checks.values()]
        overall_status = (
            "CRITICAL" if "CRITICAL" in statuses
            else "WARNING" if "WARNING" in statuses
            else "OK"
        )

        return {
            "success": True,
            "overall_risk_status": overall_status,
            "net_liquidation": net_liquidation,
            "risk_checks": risk_checks,
            "position_count": len(positions),
            "largest_position": {
                "symbol": max(position_values, key=position_values.get) if position_values else None,
                "value": largest_position,
                "percentage": concentration_risk
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Risk limit check failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def set_stop_loss_orders(
    client: Any,
    trail_percent: Optional[float] = None,
    trail_amount: Optional[float] = None
) -> Dict[str, Any]:
    """
    Automatically set stop loss orders for all positions.

    Args:
        client: IBKRClient instance
        trail_percent: Trailing stop percentage (e.g., 5 for 5%)
        trail_amount: Trailing stop dollar amount

    Returns:
        Dictionary containing:
            - success: Boolean status
            - orders_placed: List of orders placed
            - total_positions_protected: Count of positions protected
            - timestamp: Execution timestamp
    """
    try:
        positions = client.ib.positions()
        orders_placed = []

        for position in positions:
            if position.position == 0:
                continue

            contract = position.contract
            quantity = abs(position.position)
            action = "SELL" if position.position > 0 else "BUY"

            # Get current price
            ticker = client.ib.reqMktData(contract)
            await asyncio.sleep(0.5)
            current_price = ticker.marketPrice()
            client.ib.cancelMktData(contract)

            if not current_price or current_price <= 0:
                continue

            # Create trailing stop order
            # Assuming client has place_trailing_stop method
            if hasattr(client, 'place_trailing_stop'):
                if trail_percent:
                    result = await client.place_trailing_stop(
                        symbol=contract.symbol,
                        action=action,
                        quantity=quantity,
                        trail_percent=trail_percent,
                        sec_type=contract.secType,
                        exchange=contract.exchange
                    )
                elif trail_amount:
                    result = await client.place_trailing_stop(
                        symbol=contract.symbol,
                        action=action,
                        quantity=quantity,
                        trail_amount=trail_amount,
                        sec_type=contract.secType,
                        exchange=contract.exchange
                    )
                else:
                    # Default 2% trailing stop
                    result = await client.place_trailing_stop(
                        symbol=contract.symbol,
                        action=action,
                        quantity=quantity,
                        trail_percent=2.0,
                        sec_type=contract.secType,
                        exchange=contract.exchange
                    )

                orders_placed.append({
                    "symbol": contract.symbol,
                    "quantity": quantity,
                    "action": action,
                    "order_id": result.get("order_id"),
                    "status": result.get("status")
                })

        return {
            "success": True,
            "orders_placed": orders_placed,
            "total_positions_protected": len(orders_placed),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Stop loss order placement failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def calculate_var(
    client: Any,
    confidence_level: float = 0.95,
    time_horizon: int = 1
) -> Dict[str, Any]:
    """
    Calculate Value at Risk for the portfolio.

    Args:
        client: IBKRClient instance
        confidence_level: Confidence level (e.g., 0.95 for 95%)
        time_horizon: Time horizon in days

    Returns:
        Dictionary containing:
            - success: Boolean status
            - portfolio_value: Total portfolio value
            - confidence_level: Confidence level used
            - time_horizon_days: Time horizon
            - parametric_var: Parametric VaR calculation
            - historical_var: Historical VaR calculation
            - interpretation: Human-readable interpretation
            - timestamp: Calculation timestamp
    """
    try:
        positions = client.ib.positions()
        if not positions:
            return {
                "success": True,
                "var": 0,
                "message": "No positions to calculate VaR",
                "timestamp": datetime.now().isoformat()
            }

        # Get historical returns for each position
        portfolio_returns = []
        position_weights = []
        total_value = 0

        for position in positions:
            if position.position == 0:
                continue

            contract = position.contract
            value = abs(position.position * position.avgCost)
            total_value += value

            # Get historical data (assuming client has this method)
            if hasattr(client, 'get_historical_data'):
                hist_data = await client.get_historical_data(
                    symbol=contract.symbol,
                    duration="60 D",
                    bar_size="1 day",
                    sec_type=contract.secType
                )

                if hist_data.get("status") == "success" and hist_data.get("data"):
                    prices = [bar["close"] for bar in hist_data["data"]]
                    returns = [
                        (prices[i] - prices[i-1]) / prices[i-1]
                        for i in range(1, len(prices))
                    ]
                    portfolio_returns.append(returns)
                    position_weights.append(value)

        if not portfolio_returns:
            return {
                "success": False,
                "error": "Could not calculate returns",
                "timestamp": datetime.now().isoformat()
            }

        # Normalize weights
        weights = np.array(position_weights) / total_value

        # Calculate portfolio returns
        min_length = min(len(r) for r in portfolio_returns)
        portfolio_returns = [r[:min_length] for r in portfolio_returns]
        portfolio_returns = np.array(portfolio_returns)

        # Weighted portfolio returns
        weighted_returns = np.dot(weights, portfolio_returns)

        # Calculate VaR
        mean_return = np.mean(weighted_returns)
        std_return = np.std(weighted_returns)

        # Parametric VaR
        var_pct = stats.norm.ppf(1 - confidence_level, mean_return, std_return)
        var_amount = total_value * var_pct * np.sqrt(time_horizon)

        # Historical VaR
        sorted_returns = np.sort(weighted_returns)
        index = int((1 - confidence_level) * len(sorted_returns))
        hist_var_pct = sorted_returns[index]
        hist_var_amount = total_value * hist_var_pct * np.sqrt(time_horizon)

        return {
            "success": True,
            "portfolio_value": total_value,
            "confidence_level": confidence_level,
            "time_horizon_days": time_horizon,
            "parametric_var": {
                "amount": abs(var_amount),
                "percentage": abs(var_pct * 100)
            },
            "historical_var": {
                "amount": abs(hist_var_amount),
                "percentage": abs(hist_var_pct * 100)
            },
            "interpretation": (
                f"With {confidence_level*100}% confidence, the portfolio will not "
                f"lose more than ${abs(var_amount):.2f} in {time_horizon} day(s)"
            ),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"VaR calculation failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
