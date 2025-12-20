"""
Advanced order management tools for IBKR MCP Server.

Provides sophisticated order types and algorithmic trading capabilities:
- Bracket orders (entry + profit target + stop loss)
- Trailing stop orders
- One-Cancels-All (OCA) order groups
- Algorithmic orders (TWAP, VWAP, Arrival Price, DarkIce, Adaptive, etc.)
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ib_async import (
    BracketOrder,
    Order,
    MarketOrder,
    LimitOrder,
    StopOrder,
    Stock,
    Option,
    Future,
    Forex,
    TagValue,
)

from ..client import IBKRClient
from ..models import OrderAction, OrderType, SecType, AlgoStrategy
from ..exceptions import OrderError, ValidationError

logger = logging.getLogger(__name__)


# =============================================================================
# Advanced Order Types
# =============================================================================


async def place_bracket_order(
    client: IBKRClient,
    symbol: str,
    action: str,
    quantity: int,
    entry_price: float,
    profit_target: float,
    stop_loss: float,
    sec_type: str = "STK",
    exchange: str = "SMART",
) -> Dict[str, Any]:
    """
    Place a bracket order (entry + profit target + stop loss).

    A bracket order consists of three orders:
    1. Parent order: Entry order at limit price
    2. Profit target: Limit order to take profit
    3. Stop loss: Stop order to limit losses

    Args:
        client: IBKR client instance
        symbol: Symbol to trade
        action: Order action (BUY/SELL)
        quantity: Number of shares/contracts
        entry_price: Entry limit price
        profit_target: Profit target limit price
        stop_loss: Stop loss price
        sec_type: Security type (STK, OPT, FUT, CASH)
        exchange: Exchange to route order (default SMART)

    Returns:
        Dict containing bracket order details with all three order IDs

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

        # Validate price logic
        if action == "BUY":
            if profit_target <= entry_price:
                raise ValidationError("Profit target must be above entry price for BUY")
            if stop_loss >= entry_price:
                raise ValidationError("Stop loss must be below entry price for BUY")
        else:  # SELL
            if profit_target >= entry_price:
                raise ValidationError("Profit target must be below entry price for SELL")
            if stop_loss <= entry_price:
                raise ValidationError("Stop loss must be above entry price for SELL")

        # Ensure client is connected
        if not client.is_connected():
            await client.connect()

        # Apply rate limiting
        await client.rate_limit()

        # Create contract
        contract = _create_contract(client, symbol, sec_type, exchange)

        # Create bracket order
        bracket = BracketOrder(
            action=action,
            quantity=quantity,
            limitPrice=entry_price,
            takeProfitLimitPrice=profit_target,
            stopLossPrice=stop_loss,
        )

        # Place the bracket order (returns list of 3 orders)
        trades = []
        for order in bracket:
            trade = client.ib.placeOrder(contract, order)
            trades.append(trade)
            await asyncio.sleep(0.1)  # Small delay between orders

        # Return order details
        result = {
            "success": True,
            "order_type": "BRACKET",
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "entry_price": entry_price,
            "profit_target": profit_target,
            "stop_loss": stop_loss,
            "parent_order_id": trades[0].order.orderId if trades else None,
            "profit_order_id": trades[1].order.orderId if len(trades) > 1 else None,
            "stop_order_id": trades[2].order.orderId if len(trades) > 2 else None,
            "status": "SUBMITTED",
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(
            f"Bracket order placed: {symbol} {action} {quantity} @ "
            f"entry={entry_price}, target={profit_target}, stop={stop_loss}"
        )

        return result

    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error placing bracket order for {symbol}: {e}")
        raise OrderError(f"Failed to place bracket order: {e}")


async def place_trailing_stop(
    client: IBKRClient,
    symbol: str,
    action: str,
    quantity: int,
    trail_amount: Optional[float] = None,
    trail_percent: Optional[float] = None,
    sec_type: str = "STK",
    exchange: str = "SMART",
) -> Dict[str, Any]:
    """
    Place a trailing stop order.

    A trailing stop order follows the market price at a specified distance,
    either as a fixed amount or percentage. When the market moves favorably,
    the stop price adjusts. When the market moves unfavorably and hits the
    stop price, the order becomes a market order.

    Args:
        client: IBKR client instance
        symbol: Symbol to trade
        action: Order action (BUY/SELL)
        quantity: Number of shares/contracts
        trail_amount: Trail by fixed amount (e.g., $2.00)
        trail_percent: Trail by percentage (e.g., 5 for 5%)
        sec_type: Security type (STK, OPT, FUT, CASH)
        exchange: Exchange to route order (default SMART)

    Returns:
        Dict containing trailing stop order details

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

        if trail_amount is None and trail_percent is None:
            raise ValidationError(
                "Either trail_amount or trail_percent must be specified"
            )

        if trail_amount is not None and trail_percent is not None:
            raise ValidationError(
                "Specify only one of trail_amount or trail_percent, not both"
            )

        # Ensure client is connected
        if not client.is_connected():
            await client.connect()

        # Apply rate limiting
        await client.rate_limit()

        # Create contract
        contract = _create_contract(client, symbol, sec_type, exchange)

        # Create trailing stop order
        order = Order()
        order.action = action
        order.totalQuantity = quantity
        order.orderType = "TRAIL"

        if trail_amount is not None:
            order.auxPrice = trail_amount  # Trail by fixed amount
        elif trail_percent is not None:
            order.trailingPercent = trail_percent  # Trail by percentage

        # Place order
        trade = client.ib.placeOrder(contract, order)

        # Wait for order confirmation
        await asyncio.sleep(1)

        result = {
            "success": True,
            "order_id": trade.order.orderId,
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "order_type": "TRAILING_STOP",
            "trail_amount": trail_amount,
            "trail_percent": trail_percent,
            "status": trade.orderStatus.status,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(
            f"Trailing stop placed: {symbol} {action} {quantity}, "
            f"trail={'$' + str(trail_amount) if trail_amount else str(trail_percent) + '%'}"
        )

        return result

    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error placing trailing stop for {symbol}: {e}")
        raise OrderError(f"Failed to place trailing stop: {e}")


async def place_one_cancels_all(
    client: IBKRClient,
    orders: List[Dict[str, Any]],
    oca_group: str,
    oca_type: int = 1,
) -> Dict[str, Any]:
    """
    Place One-Cancels-All (OCA) order group.

    An OCA group links multiple orders together. When one order fills,
    the other orders in the group are automatically cancelled (or reduced).

    Args:
        client: IBKR client instance
        orders: List of order specifications, each with:
            - symbol: Symbol to trade
            - action: Order action (BUY/SELL)
            - quantity: Number of shares/contracts
            - order_type: Order type (MKT, LMT, STP)
            - limit_price: Limit price (for LMT orders)
            - stop_price: Stop price (for STP orders)
            - sec_type: Security type (optional, default STK)
            - exchange: Exchange (optional, default SMART)
        oca_group: Unique identifier for the OCA group
        oca_type: OCA type:
            1 = Cancel all remaining orders on fill
            2 = Reduce quantity proportionally on partial fill
            3 = Reduce with overfill protection

    Returns:
        Dict containing list of OCA order details

    Raises:
        OrderError: If order placement fails
        ValidationError: If parameters are invalid
    """
    try:
        # Validate inputs
        if not orders:
            raise ValidationError("At least one order must be specified")

        if not oca_group:
            raise ValidationError("OCA group name must be specified")

        if oca_type not in [1, 2, 3]:
            raise ValidationError("OCA type must be 1, 2, or 3")

        # Ensure client is connected
        if not client.is_connected():
            await client.connect()

        # Apply rate limiting
        await client.rate_limit()

        trades = []

        for order_spec in orders:
            # Validate order spec
            required_fields = ["symbol", "action", "quantity", "order_type"]
            for field in required_fields:
                if field not in order_spec:
                    raise ValidationError(f"Order missing required field: {field}")

            # Create contract
            contract = _create_contract(
                client,
                order_spec["symbol"],
                order_spec.get("sec_type", "STK"),
                order_spec.get("exchange", "SMART"),
            )

            # Create order based on type
            order_type = order_spec["order_type"].upper()
            if order_type == "LMT":
                if "limit_price" not in order_spec:
                    raise ValidationError("limit_price required for LMT orders")
                order = LimitOrder(
                    order_spec["action"],
                    order_spec["quantity"],
                    order_spec["limit_price"],
                )
            elif order_type == "STP":
                if "stop_price" not in order_spec:
                    raise ValidationError("stop_price required for STP orders")
                order = StopOrder(
                    order_spec["action"],
                    order_spec["quantity"],
                    order_spec["stop_price"],
                )
            else:  # MKT
                order = MarketOrder(order_spec["action"], order_spec["quantity"])

            # Set OCA properties
            order.ocaGroup = oca_group
            order.ocaType = oca_type

            # Place order
            trade = client.ib.placeOrder(contract, order)
            trades.append(
                {
                    "order_id": trade.order.orderId,
                    "symbol": order_spec["symbol"],
                    "action": order_spec["action"],
                    "quantity": order_spec["quantity"],
                    "order_type": order_spec["order_type"],
                    "oca_group": oca_group,
                    "status": trade.orderStatus.status,
                }
            )

            await asyncio.sleep(0.1)  # Small delay between orders

        logger.info(
            f"OCA group '{oca_group}' placed with {len(trades)} orders, type={oca_type}"
        )

        return {
            "success": True,
            "oca_group": oca_group,
            "oca_type": oca_type,
            "orders": trades,
            "count": len(trades),
            "timestamp": datetime.now().isoformat(),
        }

    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error placing OCA orders: {e}")
        raise OrderError(f"Failed to place OCA orders: {e}")


# =============================================================================
# Algorithmic Orders
# =============================================================================


async def place_algo_order(
    client: IBKRClient,
    symbol: str,
    action: str,
    quantity: int,
    algo_strategy: str,
    algo_params: Dict[str, str],
    sec_type: str = "STK",
    exchange: str = "SMART",
) -> Dict[str, Any]:
    """
    Place an algorithmic order using IBKR's algo strategies.

    Supported strategies:
    - ArrivalPx: Arrival Price algorithm
    - DarkIce: Dark liquidity seeking
    - PctVol: Percent of Volume
    - Twap: Time-Weighted Average Price
    - Vwap: Volume-Weighted Average Price
    - AD: Accumulate/Distribute
    - BalanceImpactRisk: Balance market impact and risk
    - MinImpact: Minimize market impact
    - Adaptive: IB's adaptive algo

    Args:
        client: IBKR client instance
        symbol: Symbol to trade
        action: Order action (BUY/SELL)
        quantity: Number of shares/contracts
        algo_strategy: Algorithm strategy name
        algo_params: Algorithm-specific parameters (use helper functions)
        sec_type: Security type (STK, OPT, FUT, CASH)
        exchange: Exchange to route order (default SMART)

    Returns:
        Dict containing algo order details

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

        # Validate algo strategy
        valid_strategies = [
            "ArrivalPx",
            "DarkIce",
            "PctVol",
            "Twap",
            "Vwap",
            "AD",
            "BalanceImpactRisk",
            "MinImpact",
            "Adaptive",
        ]
        if algo_strategy not in valid_strategies:
            raise ValidationError(
                f"Invalid algo strategy: {algo_strategy}. "
                f"Must be one of: {', '.join(valid_strategies)}"
            )

        # Ensure client is connected
        if not client.is_connected():
            await client.connect()

        # Apply rate limiting
        await client.rate_limit()

        # Create contract
        contract = _create_contract(client, symbol, sec_type, exchange)

        # Create base order
        order = Order()
        order.action = action
        order.totalQuantity = quantity
        order.orderType = "LMT"  # Most algos work with limit orders

        # Set algo strategy
        order.algoStrategy = algo_strategy

        # Convert algo params to the required format (list of TagValue objects)
        order.algoParams = []
        for key, value in algo_params.items():
            order.algoParams.append(TagValue(key, str(value)))

        # Place the algo order
        trade = client.ib.placeOrder(contract, order)

        # Wait for order confirmation
        await asyncio.sleep(1)

        result = {
            "success": True,
            "order_id": trade.order.orderId,
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "algo_strategy": algo_strategy,
            "algo_params": algo_params,
            "status": trade.orderStatus.status,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(
            f"Algo order placed: {symbol} {action} {quantity}, "
            f"strategy={algo_strategy}, order_id={trade.order.orderId}"
        )

        return result

    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error placing algo order for {symbol}: {e}")
        raise OrderError(f"Failed to place algo order: {e}")


# =============================================================================
# Algo Parameter Helper Functions
# =============================================================================


def create_twap_params(
    strategy_type: str = "Marketable",
    start_time: str = "",
    end_time: str = "",
    allow_past_end_time: bool = True,
) -> Dict[str, str]:
    """
    Create parameters for TWAP (Time-Weighted Average Price) algorithm.

    TWAP divides the order into equal slices executed at regular intervals.

    Args:
        strategy_type: Execution strategy:
            - Marketable: Cross spread immediately
            - Matching: Match midpoint
            - Midpoint: Target NBBO midpoint
        start_time: Start time (format: YYYYMMDD-HH:MM:SS)
        end_time: End time (format: YYYYMMDD-HH:MM:SS)
        allow_past_end_time: Allow order to continue past end time

    Returns:
        Dict of TWAP parameters
    """
    params = {
        "strategyType": strategy_type,
        "allowPastEndTime": "1" if allow_past_end_time else "0",
    }
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    return params


def create_vwap_params(
    max_pct_vol: float = 0.1,
    start_time: str = "",
    end_time: str = "",
    allow_past_end_time: bool = True,
    no_take_liq: bool = False,
    speed_up: bool = False,
) -> Dict[str, str]:
    """
    Create parameters for VWAP (Volume-Weighted Average Price) algorithm.

    VWAP attempts to match the volume-weighted average price throughout the day.

    Args:
        max_pct_vol: Maximum percentage of volume (0.01 = 1%)
        start_time: Start time (format: YYYYMMDD-HH:MM:SS)
        end_time: End time (format: YYYYMMDD-HH:MM:SS)
        allow_past_end_time: Allow order to continue past end time
        no_take_liq: Do not take liquidity (post only)
        speed_up: Speed up when falling behind

    Returns:
        Dict of VWAP parameters
    """
    params = {
        "maxPctVol": str(max_pct_vol),
        "noTakeLiq": "1" if no_take_liq else "0",
        "speedUp": "1" if speed_up else "0",
        "allowPastEndTime": "1" if allow_past_end_time else "0",
    }
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    return params


def create_arrival_price_params(
    max_pct_vol: float = 0.1,
    risk_aversion: str = "Neutral",
    start_time: str = "",
    end_time: str = "",
    force_completion: bool = False,
    allow_past_end_time: bool = True,
) -> Dict[str, str]:
    """
    Create parameters for Arrival Price algorithm.

    Arrival Price minimizes market impact and tracks arrival price.

    Args:
        max_pct_vol: Maximum percentage of volume (0.01 = 1%)
        risk_aversion: Risk aversion level:
            - Get Done: Very aggressive
            - Aggressive: Aggressive
            - Neutral: Balanced
            - Passive: Conservative
        start_time: Start time (format: YYYYMMDD-HH:MM:SS)
        end_time: End time (format: YYYYMMDD-HH:MM:SS)
        force_completion: Force order completion by end time
        allow_past_end_time: Allow order to continue past end time

    Returns:
        Dict of Arrival Price parameters
    """
    params = {
        "maxPctVol": str(max_pct_vol),
        "riskAversion": risk_aversion,
        "forceCompletion": "1" if force_completion else "0",
        "allowPastEndTime": "1" if allow_past_end_time else "0",
    }
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    return params


def create_dark_ice_params(
    display_size: int = 0,
    start_time: str = "",
    end_time: str = "",
    allow_past_end_time: bool = True,
) -> Dict[str, str]:
    """
    Create parameters for DarkIce algorithm.

    DarkIce seeks dark pool liquidity while minimizing market impact.

    Args:
        display_size: Visible display size (0 for fully hidden)
        start_time: Start time (format: YYYYMMDD-HH:MM:SS)
        end_time: End time (format: YYYYMMDD-HH:MM:SS)
        allow_past_end_time: Allow order to continue past end time

    Returns:
        Dict of DarkIce parameters
    """
    params = {
        "displaySize": str(display_size),
        "allowPastEndTime": "1" if allow_past_end_time else "0",
    }
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    return params


def create_adaptive_params(priority: str = "Normal") -> Dict[str, str]:
    """
    Create parameters for Adaptive algorithm.

    IB's adaptive algorithm adjusts to market conditions.

    Args:
        priority: Execution urgency:
            - Urgent: Very aggressive
            - High: Aggressive
            - Normal: Balanced
            - Low: Patient
            - Patient: Very patient

    Returns:
        Dict of Adaptive parameters
    """
    return {"adaptivePriority": priority}


def create_accumulate_distribute_params(
    component_size: int = 100,
    time_between_orders: int = 60,
    randomize_time: bool = True,
    randomize_size: bool = True,
    give_up: int = 1,
    catch_up: bool = True,
    wait_for_fill: bool = False,
) -> Dict[str, str]:
    """
    Create parameters for Accumulate/Distribute algorithm.

    Breaks order into smaller components with time intervals.

    Args:
        component_size: Size of each component order
        time_between_orders: Seconds between orders
        randomize_time: Randomize time between orders (+/- 20%)
        randomize_size: Randomize component size (+/- 55%)
        give_up: Minutes to wait before cancelling unfilled order
        catch_up: Increase order size if behind schedule
        wait_for_fill: Wait for fill before submitting next order

    Returns:
        Dict of Accumulate/Distribute parameters
    """
    return {
        "componentSize": str(component_size),
        "timeBetweenOrders": str(time_between_orders),
        "randomizeTime20": "1" if randomize_time else "0",
        "randomizeSize55": "1" if randomize_size else "0",
        "giveUp": str(give_up),
        "catchUp": "1" if catch_up else "0",
        "waitForFill": "1" if wait_for_fill else "0",
    }


def create_balance_impact_risk_params(
    max_pct_vol: float = 0.1,
    risk_aversion: str = "Neutral",
    force_completion: bool = False,
) -> Dict[str, str]:
    """
    Create parameters for Balance Impact Risk algorithm.

    Balances market impact against execution risk.

    Args:
        max_pct_vol: Maximum percentage of volume (0.01 = 1%)
        risk_aversion: Risk aversion level (Get Done, Aggressive, Neutral, Passive)
        force_completion: Force order completion

    Returns:
        Dict of Balance Impact Risk parameters
    """
    return {
        "maxPctVol": str(max_pct_vol),
        "riskAversion": risk_aversion,
        "forceCompletion": "1" if force_completion else "0",
    }


def create_min_impact_params(max_pct_vol: float = 0.1) -> Dict[str, str]:
    """
    Create parameters for Minimize Impact algorithm.

    Minimizes market impact while executing the order.

    Args:
        max_pct_vol: Maximum percentage of volume (0.01 = 1%)

    Returns:
        Dict of Minimize Impact parameters
    """
    return {"maxPctVol": str(max_pct_vol)}


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
