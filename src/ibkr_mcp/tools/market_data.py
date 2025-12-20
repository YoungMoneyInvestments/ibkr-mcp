"""
Market data retrieval tools for IBKR MCP Server.

This module provides comprehensive market data access including:
- Real-time pricing with fast failover
- Historical data with pagination and futures support
- HFT streaming capabilities
- Level 2 order book data
- Execution slippage analysis
- News bulletins
- Symbol search
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from ..exceptions import DataError, MarketDataError
from ..models import TickData, BarData, OrderBook, SecType

logger = logging.getLogger(__name__)


# =============================================================================
# Real-time Price Data
# =============================================================================


async def get_realtime_price(
    client: Any,  # IBKRClient - typed as Any to avoid circular import
    symbol: str,
    sec_type: str = "STK",
    exchange: str = "SMART"
) -> Dict[str, Any]:
    """
    Get real-time price with fast failover for fallback mechanisms.

    This function implements fast timeout behavior to enable quick failover
    to alternative data sources (e.g., Yahoo Finance) when IBKR data is
    unavailable.

    Args:
        client: IBKRClient instance
        symbol: Trading symbol
        sec_type: Security type (STK, OPT, FUT, etc.)
        exchange: Exchange (default: SMART)

    Returns:
        Dict containing:
            - symbol: Symbol name
            - bid: Bid price
            - ask: Ask price
            - last: Last trade price
            - close: Previous close
            - volume: Volume
            - high: High price
            - low: Low price
            - bid_size: Bid size
            - ask_size: Ask size
            - timestamp: ISO timestamp
            - market_timezone: Market timezone

    Raises:
        DataError: When no market data is available (fast fail for fallback)
        MarketDataError: For other market data errors
    """
    client._ensure_connected()

    # Apply rate limiting
    await client._rate_limiter.acquire()

    try:
        # Create contract
        contract = client._create_contract(symbol, sec_type, exchange)

        # Request market data
        client.ib.reqMktData(contract, '', False, False)

        # Use configured data timeout for fast failover
        await asyncio.sleep(client.config.data_timeout)

        ticker = client.ib.ticker(contract)

        # Cancel market data
        client.ib.cancelMktData(contract)

        # Check if we got valid data
        if ticker.last is None or ticker.last == -1:
            # No data - fail fast without triggering reconnection
            raise DataError(f"No market data available for {symbol} - try alternative data source")

        # Convert ticker to clean dictionary
        result = {
            'success': True,
            'data': _ticker_to_dict(ticker, client),
            'timestamp': datetime.now().isoformat()
        }

        return result

    except DataError:
        # Data errors don't trigger reconnection - fast fail for fallback
        raise
    except Exception as e:
        logger.warning(f"Failed to get price for {symbol}: {e}")
        raise MarketDataError(f"IBKR data unavailable for {symbol}: {str(e)}")


# =============================================================================
# Historical Data
# =============================================================================


async def get_historical_data(
    client: Any,
    symbol: str,
    duration: str = "1 D",
    bar_size: str = "1 hour",
    sec_type: str = "STK",
    exchange: str = "SMART",
    use_continuous: bool = True,
    specific_expiry: Optional[str] = None,
    page: int = 1,
    page_size: int = 100
) -> Dict[str, Any]:
    """
    Get historical bar data with proper contract handling and pagination.

    For futures contracts:
    - use_continuous=True: Use continuous contract for long-term analysis
    - use_continuous=False: Use front month contract
    - specific_expiry: Use specific contract like 'ESZ5'

    Args:
        client: IBKRClient instance
        symbol: Trading symbol
        duration: Duration string (e.g., "1 D", "1 W", "1 M", "1 Y")
        bar_size: Bar size (e.g., "1 min", "5 mins", "1 hour", "1 day")
        sec_type: Security type (STK, OPT, FUT, etc.)
        exchange: Exchange (default: SMART)
        use_continuous: Use continuous futures contract (futures only)
        specific_expiry: Specific expiry for futures (e.g., "ESZ5")
        page: Page number for pagination (1-indexed)
        page_size: Number of bars per page

    Returns:
        Dict containing:
            - success: Success status
            - data: Dictionary with:
                - symbol: Symbol name
                - duration: Duration string
                - bar_size: Bar size string
                - sec_type: Security type
                - data: List of bar dictionaries
                - pagination: Pagination metadata
                - meta: Request metadata
            - timestamp: ISO timestamp

    Raises:
        MarketDataError: On data retrieval failure
    """
    client._ensure_connected()

    # Apply rate limiting
    await client._rate_limiter.acquire()

    try:
        # Smart contract creation based on type and requirements
        if sec_type.upper() == "FUT":
            contract = client._smart_contract_lookup(
                symbol, sec_type, exchange,
                use_continuous=use_continuous,
                specific_expiry=specific_expiry
            )
        else:
            contract = client._create_contract(symbol, sec_type, exchange)

        # Request historical data
        bars = client.ib.reqHistoricalData(
            contract,
            endDateTime='',
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow='TRADES',
            useRTH=True,
            formatDate=1
        )

        # Convert to clean structure
        all_data = [
            {
                'date': bar.date.isoformat(),
                'open': float(bar.open),
                'high': float(bar.high),
                'low': float(bar.low),
                'close': float(bar.close),
                'volume': int(bar.volume),
                'average': float(bar.average),
                'barCount': int(bar.barCount)
            }
            for bar in bars
        ]

        # Apply pagination
        total_bars = len(all_data)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        paginated_data = all_data[start_idx:end_idx]

        result = {
            'success': True,
            'data': {
                'symbol': symbol,
                'duration': duration,
                'bar_size': bar_size,
                'sec_type': sec_type,
                'data': paginated_data,
                'pagination': {
                    'page': page,
                    'page_size': page_size,
                    'total_bars': total_bars,
                    'total_pages': (total_bars + page_size - 1) // page_size,
                    'has_next': end_idx < total_bars,
                    'has_previous': page > 1
                },
                'meta': {
                    'timestamp': client._get_local_time().isoformat(),
                    'contract_type': 'continuous' if sec_type == 'FUT' and use_continuous else 'specific',
                    'timezone': client.config.market_timezone
                }
            },
            'timestamp': datetime.now().isoformat()
        }

        return result

    except Exception as e:
        logger.error(f"Error getting historical data for {symbol}: {e}")
        raise MarketDataError(f"Failed to retrieve historical data: {str(e)}")


# =============================================================================
# HFT Streaming
# =============================================================================


async def stream_market_data(
    client: Any,
    symbols: List[str],
    data_type: str = "TRADES"
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream real-time market data for HFT strategies.

    This function yields market data updates in real-time with minimal latency
    (1ms polling interval) suitable for high-frequency trading strategies.

    Args:
        client: IBKRClient instance
        symbols: List of symbols to stream
        data_type: Data type to stream:
            - "TRADES": Trade data (price, size)
            - "BID_ASK": Quote data (bid, ask, sizes)
            - "ALL": Both trades and quotes

    Yields:
        Dict containing either:
            Trade data:
                - type: "trade"
                - symbol: Symbol name
                - price: Last trade price
                - size: Last trade size
                - time: Trade timestamp
            Quote data:
                - type: "quote"
                - symbol: Symbol name
                - bid: Bid price
                - ask: Ask price
                - bid_size: Bid size
                - ask_size: Ask size
                - spread: Bid-ask spread

    Raises:
        MarketDataError: On streaming setup failure
    """
    client._ensure_connected()

    try:
        # Create and qualify contracts
        from ib_async import Stock

        contracts = []
        for symbol in symbols:
            contract = Stock(symbol, "SMART", "USD")
            client.ib.qualifyContracts(contract)
            contracts.append(contract)

        # Subscribe to market data
        tickers = []
        for contract in contracts:
            ticker = client.ib.reqMktData(
                contract,
                genericTickList="",
                snapshot=False,
                regulatorySnapshot=False
            )
            tickers.append(ticker)

        try:
            while True:
                await asyncio.sleep(0.001)  # 1ms polling for HFT

                for ticker in tickers:
                    if data_type in ["TRADES", "ALL"] and ticker.last:
                        yield {
                            "type": "trade",
                            "symbol": ticker.contract.symbol,
                            "price": ticker.last,
                            "size": ticker.lastSize,
                            "time": ticker.time
                        }

                    if data_type in ["BID_ASK", "ALL"]:
                        if ticker.bid and ticker.ask:
                            yield {
                                "type": "quote",
                                "symbol": ticker.contract.symbol,
                                "bid": ticker.bid,
                                "ask": ticker.ask,
                                "bid_size": ticker.bidSize,
                                "ask_size": ticker.askSize,
                                "spread": ticker.ask - ticker.bid
                            }

        finally:
            # Clean up subscriptions
            for contract in contracts:
                client.ib.cancelMktData(contract)

    except Exception as e:
        logger.error(f"Streaming failed for {symbols}: {e}")
        raise MarketDataError(f"Failed to stream market data: {str(e)}")


# =============================================================================
# Order Book (Level 2)
# =============================================================================


async def get_order_book(
    client: Any,
    symbol: str,
    depth: int = 5
) -> Dict[str, Any]:
    """
    Get Level 2 order book data (market depth).

    Args:
        client: IBKRClient instance
        symbol: Trading symbol
        depth: Number of price levels to retrieve (default: 5)

    Returns:
        Dict containing:
            - success: Success status
            - data: Dictionary with:
                - symbol: Symbol name
                - bids: List of bid levels with price, size, cumulative_size
                - asks: List of ask levels with price, size, cumulative_size
                - spread: Bid-ask spread
                - mid_price: Mid-market price
                - imbalance: Order book imbalance (bid volume - ask volume)
            - timestamp: ISO timestamp

    Raises:
        MarketDataError: On order book retrieval failure
    """
    client._ensure_connected()

    try:
        from ib_async import Stock

        contract = Stock(symbol, "SMART", "USD")
        client.ib.qualifyContracts(contract)

        # Request market depth
        depth_data = client.ib.reqMktDepth(contract, numRows=depth)
        await asyncio.sleep(0.5)  # Wait for data

        bids = []
        asks = []

        for i in range(depth):
            if i < len(depth_data.bids):
                bid = depth_data.bids[i]
                bids.append({
                    "price": bid.price,
                    "size": bid.size,
                    "cumulative_size": sum(b.size for b in depth_data.bids[:i+1])
                })

            if i < len(depth_data.asks):
                ask = depth_data.asks[i]
                asks.append({
                    "price": ask.price,
                    "size": ask.size,
                    "cumulative_size": sum(a.size for a in depth_data.asks[:i+1])
                })

        # Calculate metrics
        if bids and asks:
            spread = asks[0]["price"] - bids[0]["price"]
            mid_price = (asks[0]["price"] + bids[0]["price"]) / 2
            imbalance = sum(b["size"] for b in bids) - sum(a["size"] for a in asks)
        else:
            spread = mid_price = imbalance = 0

        client.ib.cancelMktDepth(contract)

        return {
            "success": True,
            "data": {
                "symbol": symbol,
                "bids": bids,
                "asks": asks,
                "spread": spread,
                "mid_price": mid_price,
                "imbalance": imbalance
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Order book retrieval failed for {symbol}: {e}")
        raise MarketDataError(f"Failed to retrieve order book: {str(e)}")


# =============================================================================
# Slippage Analysis
# =============================================================================


async def calculate_slippage(
    client: Any,
    order_id: int
) -> Dict[str, Any]:
    """
    Calculate execution slippage for an order.

    Analyzes the difference between intended execution price and actual
    average fill price, including implementation shortfall metrics.

    Args:
        client: IBKRClient instance
        order_id: Order ID to analyze

    Returns:
        Dict containing:
            - success: Success status
            - data: Dictionary with:
                - order_id: Order ID
                - intended_price: Intended execution price
                - avg_fill_price: Average fill price
                - slippage: Absolute slippage
                - slippage_pct: Slippage percentage
                - implementation_shortfall: Implementation shortfall
                - total_quantity: Total quantity filled
                - num_fills: Number of fills
            - timestamp: ISO timestamp

    Raises:
        MarketDataError: On slippage calculation failure
    """
    client._ensure_connected()

    try:
        # Get order and execution details
        order = client.ib.order(order_id)
        executions = client.ib.executions(orderId=order_id)

        if not executions:
            raise MarketDataError("No executions found for order")

        # Calculate metrics
        intended_price = order.lmtPrice if order.orderType == "LMT" else order.auxPrice

        total_quantity = sum(e.shares for e in executions)
        avg_fill_price = sum(e.price * e.shares for e in executions) / total_quantity

        slippage = avg_fill_price - intended_price
        slippage_pct = (slippage / intended_price) * 100 if intended_price else 0

        # Implementation shortfall
        arrival_price = executions[0].price if executions else intended_price
        implementation_shortfall = (avg_fill_price - arrival_price) * total_quantity

        return {
            "success": True,
            "data": {
                "order_id": order_id,
                "intended_price": float(intended_price) if intended_price else None,
                "avg_fill_price": float(avg_fill_price),
                "slippage": float(slippage),
                "slippage_pct": float(slippage_pct),
                "implementation_shortfall": float(implementation_shortfall),
                "total_quantity": int(total_quantity),
                "num_fills": len(executions)
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Slippage calculation failed for order {order_id}: {e}")
        raise MarketDataError(f"Failed to calculate slippage: {str(e)}")


# =============================================================================
# News Data
# =============================================================================


async def get_news(
    client: Any,
    symbol: str,
    sec_type: str = "STK",
    exchange: str = "SMART"
) -> Dict[str, Any]:
    """
    Get news bulletins for a symbol.

    Note: Detailed news articles require IBKR news subscription.
    Free tier provides general market bulletins.

    Args:
        client: IBKRClient instance
        symbol: Trading symbol
        sec_type: Security type (default: STK)
        exchange: Exchange (default: SMART)

    Returns:
        Dict containing:
            - success: Success status
            - data: Dictionary with:
                - symbol: Symbol name
                - bulletins: List of news bulletins
                - note: Subscription note
            - timestamp: ISO timestamp

    Raises:
        MarketDataError: On news retrieval failure
    """
    client._ensure_connected()

    # Apply rate limiting
    await client._rate_limiter.acquire()

    try:
        # Create contract
        contract = client._create_contract(symbol, sec_type, exchange)

        # Request news bulletins (free, no subscription needed)
        bulletins = client.ib.reqNewsBulletins(allMessages=True)

        # Cancel bulletin subscription
        client.ib.cancelNewsBulletins()

        return {
            'success': True,
            'data': {
                'symbol': symbol,
                'bulletins': bulletins if bulletins else [],
                'note': 'Detailed news requires IBKR news subscription'
            },
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.warning(f"News not available for {symbol}: {e}")
        return {
            'success': False,
            'data': {
                'symbol': symbol,
                'bulletins': []
            },
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


# =============================================================================
# Symbol Search
# =============================================================================


async def search_symbols(
    client: Any,
    pattern: str
) -> Dict[str, Any]:
    """
    Search for tradable instruments matching pattern.

    Uses IBKR's symbol search to find matching contracts across all
    security types and exchanges.

    Args:
        client: IBKRClient instance
        pattern: Search pattern (partial symbol, company name, etc.)

    Returns:
        Dict containing:
            - success: Success status
            - data: List of matching symbols with:
                - symbol: Symbol name
                - name: Full name/description
                - sec_type: Security type
                - currency: Trading currency
                - exchange: Primary exchange
                - con_id: Contract ID
                - primary_exchange: Primary exchange
            - timestamp: ISO timestamp

    Raises:
        MarketDataError: On search failure
    """
    client._ensure_connected()

    # Apply rate limiting
    await client._rate_limiter.acquire()

    try:
        # Use IB's symbol search
        results = client.ib.reqMatchingSymbols(pattern)

        symbols = []
        for result in results:
            contract = result.contract
            symbols.append({
                'symbol': contract.symbol,
                'name': contract.longName or contract.localSymbol,
                'sec_type': contract.secType,
                'currency': contract.currency,
                'exchange': contract.exchange,
                'con_id': contract.conId,
                'primary_exchange': contract.primaryExchange
            })

        return {
            'success': True,
            'data': symbols,
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error searching symbols for pattern '{pattern}': {e}")
        raise MarketDataError(f"Failed to search symbols: {str(e)}")


# =============================================================================
# Helper Functions
# =============================================================================


def _ticker_to_dict(ticker: Any, client: Any) -> Dict[str, Any]:
    """
    Convert IBKR ticker to clean dictionary.

    Args:
        ticker: IBKR ticker object
        client: IBKRClient instance for timezone access

    Returns:
        Dict with cleaned ticker data
    """
    return {
        'symbol': ticker.contract.symbol if ticker.contract else None,
        'bid': float(ticker.bid) if ticker.bid and ticker.bid != -1 else None,
        'ask': float(ticker.ask) if ticker.ask and ticker.ask != -1 else None,
        'last': float(ticker.last) if ticker.last and ticker.last != -1 else None,
        'close': float(ticker.close) if ticker.close and ticker.close != -1 else None,
        'volume': int(ticker.volume) if ticker.volume and ticker.volume != -1 else None,
        'high': float(ticker.high) if ticker.high and ticker.high != -1 else None,
        'low': float(ticker.low) if ticker.low and ticker.low != -1 else None,
        'bid_size': int(ticker.bidSize) if ticker.bidSize and ticker.bidSize != -1 else None,
        'ask_size': int(ticker.askSize) if ticker.askSize and ticker.askSize != -1 else None,
        'timestamp': client._get_market_time().isoformat(),
        'market_timezone': client.config.market_timezone
    }
