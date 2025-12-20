"""
Options trading tools for IBKR MCP Server.

Provides options chain retrieval, Greeks analysis, and spread strategy evaluation.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ib_async import Stock, Option

from ..exceptions import DataError, ValidationError

logger = logging.getLogger(__name__)


async def get_option_chain(
    client: Any,
    symbol: str,
    exchange: str = "SMART"
) -> Dict[str, Any]:
    """
    Get option chain with Greeks and analysis.

    Args:
        client: IBKRClient instance
        symbol: Underlying symbol (e.g., 'AAPL')
        exchange: Exchange (default: SMART)

    Returns:
        Dictionary containing:
            - symbol: Underlying symbol
            - underlying_price: Current price of underlying
            - option_count: Number of options returned
            - expirations: List of expiration dates
            - options: List of option contracts with Greeks
            - timestamp: Query timestamp
    """
    try:
        # Create underlying stock contract
        underlying = Stock(symbol, exchange, 'USD')

        # Get option chain
        chains = client.ib.reqSecDefOptParams(
            underlying.symbol,
            '',
            underlying.secType,
            underlying.conId
        )

        if not chains:
            return {
                'success': False,
                'symbol': symbol,
                'chains': [],
                'error': 'No option chains found',
                'timestamp': datetime.now().isoformat()
            }

        chain = chains[0]

        # Get current price of underlying
        ticker = client.ib.reqMktData(underlying, '', False, False)
        await asyncio.sleep(2)  # Wait for data
        underlying_price = ticker.last if ticker.last and ticker.last != -1 else ticker.close

        # Get option contracts for nearest expirations
        option_data = []
        expirations = sorted(chain.expirations)[:3]  # Get next 3 expirations

        for expiry in expirations:
            # Get strikes near the money
            if underlying_price:
                strikes = [
                    s for s in chain.strikes
                    if abs(s - underlying_price) / underlying_price <= 0.15
                ]  # Within 15% of spot
            else:
                strikes = chain.strikes[:10]  # Fallback to first 10 strikes

            for strike in strikes:
                for right in ['C', 'P']:  # Calls and Puts
                    option = Option(symbol, expiry, strike, right, exchange)

                    # Get option details and market data
                    details = client.ib.reqContractDetails(option)
                    if details:
                        opt_contract = details[0].contract
                        opt_ticker = client.ib.reqMktData(opt_contract, '', False, False)
                        await asyncio.sleep(0.1)

                        # Extract Greeks and market data
                        option_info = {
                            'symbol': symbol,
                            'expiry': expiry,
                            'strike': strike,
                            'right': right,
                            'bid': float(opt_ticker.bid) if opt_ticker.bid and opt_ticker.bid != -1 else None,
                            'ask': float(opt_ticker.ask) if opt_ticker.ask and opt_ticker.ask != -1 else None,
                            'last': float(opt_ticker.last) if opt_ticker.last and opt_ticker.last != -1 else None,
                            'volume': int(opt_ticker.volume) if opt_ticker.volume and opt_ticker.volume != -1 else None,
                            'openInterest': opt_ticker.lastGreeks.optPrice if hasattr(opt_ticker, 'lastGreeks') else None,
                            'impliedVol': opt_ticker.lastGreeks.impliedVol if hasattr(opt_ticker, 'lastGreeks') else None,
                            'delta': opt_ticker.lastGreeks.delta if hasattr(opt_ticker, 'lastGreeks') else None,
                            'gamma': opt_ticker.lastGreeks.gamma if hasattr(opt_ticker, 'lastGreeks') else None,
                            'theta': opt_ticker.lastGreeks.theta if hasattr(opt_ticker, 'lastGreeks') else None,
                            'vega': opt_ticker.lastGreeks.vega if hasattr(opt_ticker, 'lastGreeks') else None
                        }
                        option_data.append(option_info)

        # Cancel market data subscriptions
        client.ib.cancelMktData(ticker)

        return {
            'success': True,
            'symbol': symbol,
            'underlying_price': underlying_price,
            'option_count': len(option_data),
            'expirations': expirations,
            'options': option_data,
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error getting option chain for {symbol}: {e}")
        raise DataError(f"Failed to get option chain: {e}")


async def analyze_option_spread(
    client: Any,
    symbol: str,
    strategy: str,
    strike1: float,
    strike2: Optional[float] = None,
    expiry: Optional[str] = None,
    quantity: int = 1
) -> Dict[str, Any]:
    """
    Analyze option spread strategies.

    Args:
        client: IBKRClient instance
        symbol: Underlying symbol
        strategy: Strategy name (bull_call, bear_put, bull_put, bear_call,
                  straddle, strangle, iron_condor)
        strike1: First strike price
        strike2: Second strike price (if applicable)
        expiry: Expiration date (YYYYMMDD format)
        quantity: Number of spreads

    Returns:
        Dictionary containing:
            - strategy: Strategy name
            - symbol: Underlying symbol
            - underlying_price: Current underlying price
            - legs: List of option legs with prices
            - total_cost: Net debit/credit
            - max_profit: Maximum profit
            - max_loss: Maximum loss
            - breakeven: Breakeven price(s)
            - timestamp: Query timestamp
    """
    try:
        # Define strategy configurations
        strategies = {
            'bull_call': {'legs': [('C', 'BUY', strike1), ('C', 'SELL', strike2)]},
            'bear_put': {'legs': [('P', 'BUY', strike2), ('P', 'SELL', strike1)]},
            'bull_put': {'legs': [('P', 'SELL', strike2), ('P', 'BUY', strike1)]},
            'bear_call': {'legs': [('C', 'SELL', strike1), ('C', 'BUY', strike2)]},
            'straddle': {'legs': [('C', 'BUY', strike1), ('P', 'BUY', strike1)]},
            'strangle': {'legs': [('C', 'BUY', strike2), ('P', 'BUY', strike1)]},
            'iron_condor': {'legs': [
                ('P', 'SELL', strike1 - 10),
                ('P', 'BUY', strike1 - 20),
                ('C', 'SELL', strike1 + 10),
                ('C', 'BUY', strike1 + 20)
            ]}
        }

        if strategy not in strategies:
            raise ValidationError(
                f"Unknown strategy: {strategy}. Valid: {list(strategies.keys())}"
            )

        spread_info = strategies[strategy]

        # Get underlying price
        underlying = Stock(symbol, 'SMART', 'USD')
        ticker = client.ib.reqMktData(underlying, '', False, False)
        await asyncio.sleep(2)
        underlying_price = ticker.last if ticker.last and ticker.last != -1 else ticker.close

        # Calculate spread metrics
        total_cost = 0
        max_profit = 0
        max_loss = 0
        breakeven = []

        legs_data = []
        for right, action, strike in spread_info['legs']:
            option = Option(symbol, expiry or '20250117', strike, right, 'SMART')
            opt_ticker = client.ib.reqMktData(option, '', False, False)
            await asyncio.sleep(0.1)

            price = opt_ticker.last if opt_ticker.last and opt_ticker.last != -1 else 0

            leg_data = {
                'right': right,
                'action': action,
                'strike': strike,
                'price': price,
                'cost': price * quantity * 100 * (1 if action == 'BUY' else -1)
            }
            legs_data.append(leg_data)
            total_cost += leg_data['cost']

        # Calculate P&L scenarios
        if strategy == 'bull_call':
            max_profit = (strike2 - strike1) * quantity * 100 - total_cost
            max_loss = total_cost
            breakeven = [strike1 + total_cost / (quantity * 100)]
        elif strategy == 'straddle':
            max_profit = float('inf')  # Unlimited
            max_loss = total_cost
            breakeven = [
                strike1 - total_cost / (quantity * 100),
                strike1 + total_cost / (quantity * 100)
            ]

        # Cancel market data
        client.ib.cancelMktData(ticker)

        return {
            'success': True,
            'strategy': strategy,
            'symbol': symbol,
            'underlying_price': underlying_price,
            'legs': legs_data,
            'total_cost': total_cost,
            'max_profit': max_profit,
            'max_loss': max_loss,
            'breakeven': breakeven,
            'quantity': quantity,
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error analyzing option spread: {e}")
        raise DataError(f"Failed to analyze option spread: {e}")
