"""
IBKR Client wrapper for async operations.

This module provides a comprehensive async wrapper around the IBKR API with:
- Connection management with exponential backoff
- Rate limiting (token bucket algorithm)
- Contract caching with LRU behavior
- Timezone handling for market data
- Event/notification callback system
- Clean async patterns

Consolidated from:
- ibkr-enhanced/src/ibkr_mcp_server/client.py: clean async patterns
- IBKR_MCP/IBKR_MCP.py: advanced features (rate limiter, timezone, caching, events)
"""

import asyncio
import time
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set

import pytz
from ib_async import IB, Contract as IBContract, Order as IBOrder, Trade
from ib_async import Stock, Option, Future, Forex
from loguru import logger

from .config import IBKRConfig
from .models import (
    Contract, Order, Position, AccountSummary,
    TickData, BarData, SecType, OrderAction, OrderType, TimeInForce
)
from .exceptions import (
    ConnectionError, OrderError, MarketDataError, DataError,
    RateLimitError
)


# ============================================================================
# Rate Limiting
# ============================================================================

class TokenBucketRateLimiter:
    """Token bucket rate limiter to prevent API throttling."""

    def __init__(self, max_requests: int = 50, time_window: float = 1.0):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in time window
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = timedelta(seconds=time_window)
        self.requests = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """
        Acquire permission to make a request.

        Returns:
            True if permission granted (always, after waiting if needed)
        """
        async with self._lock:
            now = datetime.now()

            # Remove old requests outside time window
            while self.requests and self.requests[0] < now - self.time_window:
                self.requests.popleft()

            # If at limit, wait until oldest request expires
            if len(self.requests) >= self.max_requests:
                sleep_time = (self.requests[0] + self.time_window - now).total_seconds()
                if sleep_time > 0:
                    logger.debug(f"Rate limit reached, waiting {sleep_time:.2f}s")
                    await asyncio.sleep(sleep_time)
                    return await self.acquire()

            # Record this request
            self.requests.append(now)
            return True


# ============================================================================
# IBKR Client
# ============================================================================

class IBKRClient:
    """
    Async wrapper for Interactive Brokers API.

    Features:
    - Automatic reconnection with exponential backoff
    - Rate limiting to prevent API throttling
    - Contract caching for improved performance
    - Timezone-aware datetime handling
    - Event notification system
    - Clean async/await interface
    """

    def __init__(self, config: IBKRConfig):
        """
        Initialize IBKR client.

        Args:
            config: IBKR configuration
        """
        self.config = config
        self.ib = IB()
        self._connected = False
        self._active_client_id: Optional[int] = None  # Tracks the client ID that successfully connected
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = config.max_reconnect_attempts

        # Rate limiter
        self._rate_limiter = TokenBucketRateLimiter(
            max_requests=int(config.requests_per_second),
            time_window=1.0
        )

        # Contract caching
        self._contract_cache: Dict[str, IBContract] = {}
        self._conid_map: Dict[int, IBContract] = {}
        self._max_cache_size = 1000  # LRU cache size limit

        # Event callbacks
        self._notification_callbacks: List[Callable] = []
        self._event_handlers: Dict[str, List[Callable]] = {}

        # Timezone handling
        self._setup_timezone()

        # Connection lock for thread-safety
        self._connection_lock = asyncio.Lock()

        # Heartbeat tracking
        self._last_heartbeat = 0
        self._heartbeat_task: Optional[asyncio.Task] = None

    def _setup_timezone(self) -> None:
        """Setup timezone handling for market data."""
        # Market timezone (default: US Eastern for US markets)
        self.market_tz = pytz.timezone(self.config.market_timezone)

        # Local timezone (auto-detect)
        try:
            import tzlocal
            self.local_tz = tzlocal.get_localzone()
        except ImportError:
            # Fallback to UTC if tzlocal not available
            self.local_tz = pytz.UTC
            logger.info("Using UTC as local timezone (install tzlocal for auto-detection)")

    def _get_market_time(self) -> datetime:
        """Get current time in market timezone."""
        return datetime.now(self.market_tz)

    def _get_local_time(self) -> datetime:
        """Get current time in local timezone."""
        return datetime.now(self.local_tz)

    def _convert_to_market_time(self, dt: datetime) -> datetime:
        """Convert datetime to market timezone."""
        if dt.tzinfo is None:
            # Assume local timezone if naive
            dt = self.local_tz.localize(dt)
        return dt.astimezone(self.market_tz)

    async def rate_limit(self) -> None:
        """Acquire a rate limiter token before making an API call."""
        await self._rate_limiter.acquire()

    # ========================================================================
    # Connection Management
    # ========================================================================

    async def connect(self) -> bool:
        """
        Connect to IBKR TWS/Gateway with retry logic.

        Supports automatic client ID retry if the initial ID is already in use.
        This is controlled by config.client_id_auto_retry and config.client_id_max_attempts.

        Returns:
            True if connected successfully

        Raises:
            ConnectionError: If connection fails after all retries
        """
        async with self._connection_lock:
            if self._connected and self.ib.isConnected():
                logger.info("Already connected to IBKR")
                return True

            mode_desc = self.config.get_mode_description()
            logger.info(f"Connecting to IBKR at {self.config.host}:{self.config.port} ({mode_desc})")

            # Determine retry settings
            max_attempts = self.config.client_id_max_attempts if self.config.client_id_auto_retry else 1
            current_client_id = self.config.client_id
            last_error = None

            for attempt in range(max_attempts):
                try:
                    logger.debug(f"Connection attempt {attempt + 1}/{max_attempts} with client_id={current_client_id}")

                    await asyncio.wait_for(
                        self.ib.connectAsync(
                            host=self.config.host,
                            port=self.config.port,
                            clientId=current_client_id,
                            timeout=self.config.timeout,
                            readonly=self.config.readonly
                        ),
                        timeout=self.config.timeout
                    )

                    self._connected = True
                    self._reconnect_attempts = 0
                    self._active_client_id = current_client_id  # Track the ID that worked

                    # Start heartbeat monitoring
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                    logger.info(f"Successfully connected to IBKR (client_id={current_client_id}, mode={mode_desc})")
                    await self._fire_event('connected', {
                        'timestamp': self._get_local_time().isoformat(),
                        'client_id': current_client_id,
                        'mode': mode_desc
                    })

                    return True

                except asyncio.TimeoutError:
                    logger.error("Connection timeout")
                    raise ConnectionError("Connection timeout")

                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()

                    # Check if this is a client ID conflict error
                    is_client_id_conflict = (
                        "client id" in error_str or
                        "clientid" in error_str or
                        "already in use" in error_str or
                        "duplicate" in error_str
                    )

                    if is_client_id_conflict and self.config.client_id_auto_retry and attempt < max_attempts - 1:
                        current_client_id += 1
                        logger.warning(f"Client ID conflict, retrying with client_id={current_client_id}")
                        # Small delay before retry
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        # Non-retryable error or out of attempts
                        break

            # All attempts failed
            logger.error(f"Failed to connect to IBKR after {max_attempts} attempts: {last_error}")
            raise ConnectionError(f"Connection failed: {last_error}")

    async def disconnect(self) -> None:
        """Disconnect from IBKR gracefully."""
        if not self._connected:
            return

        logger.info("Disconnecting from IBKR...")

        # Cancel heartbeat task
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Disconnect
        try:
            self.ib.disconnect()
        except Exception as e:
            logger.debug(f"Exception during disconnect: {e}")

        # Clear caches
        self._contract_cache.clear()
        self._conid_map.clear()

        self._connected = False

        logger.info("Disconnected from IBKR")
        await self._fire_event('disconnected', {'timestamp': self._get_local_time().isoformat()})

    def is_connected(self) -> bool:
        """Check if connected to IBKR."""
        return self._connected and self.ib.isConnected()

    async def reconnect(self) -> bool:
        """
        Attempt to reconnect to IBKR with exponential backoff.

        Returns:
            True if reconnected successfully

        Raises:
            ConnectionError: If maximum reconnection attempts exceeded
        """
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            raise ConnectionError("Maximum reconnection attempts exceeded")

        self._reconnect_attempts += 1

        # Calculate exponential backoff delay
        base_delay = self.config.reconnect_delay
        delay = min(base_delay * (2 ** (self._reconnect_attempts - 1)), 60.0)

        logger.warning(
            f"Attempting reconnection ({self._reconnect_attempts}/{self._max_reconnect_attempts}) "
            f"after {delay:.1f}s delay"
        )

        try:
            await self.disconnect()
            await asyncio.sleep(delay)
            return await self.connect()
        except Exception as e:
            logger.error(f"Reconnection attempt {self._reconnect_attempts} failed: {e}")
            if self._reconnect_attempts >= self._max_reconnect_attempts:
                raise ConnectionError(f"All reconnection attempts failed: {e}")
            return False

    async def _heartbeat_loop(self) -> None:
        """Monitor connection health with periodic heartbeats."""
        heartbeat_interval = 30.0  # seconds

        while self._connected:
            try:
                await asyncio.sleep(heartbeat_interval)

                # Request server time as heartbeat
                server_time = self.ib.reqCurrentTime()
                self._last_heartbeat = time.time()

                logger.debug(f"Heartbeat OK - Server time: {server_time}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
                # Attempt reconnection
                asyncio.create_task(self.reconnect())
                break

    def _ensure_connected(self) -> None:
        """
        Ensure connection is active.

        Raises:
            ConnectionError: If not connected
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")

    # ========================================================================
    # Contract Management
    # ========================================================================

    def _create_contract(
        self,
        symbol: str,
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD",
        **kwargs
    ) -> IBContract:
        """
        Create IBKR contract with caching.

        Args:
            symbol: Symbol/ticker
            sec_type: Security type (STK, OPT, FUT, CASH)
            exchange: Exchange
            currency: Currency
            **kwargs: Additional contract parameters

        Returns:
            IBKR Contract object
        """
        # Create cache key
        cache_key = f"{symbol}:{sec_type}:{exchange}:{currency}"

        # Check cache
        if cache_key in self._contract_cache:
            logger.debug(f"Contract cache hit: {cache_key}")
            return self._contract_cache[cache_key]

        # Create contract based on type
        sec_type = sec_type.upper()

        if sec_type == "STK":
            contract = Stock(symbol, exchange, currency)
        elif sec_type == "OPT":
            # For options, require additional parameters
            contract = Option(
                symbol=symbol,
                lastTradeDateOrContractMonth=kwargs.get('expiry', ''),
                strike=float(kwargs.get('strike', 0)),
                right=kwargs.get('right', 'C'),
                exchange=exchange,
                currency=currency
            )
        elif sec_type == "FUT":
            contract = Future(
                symbol=symbol,
                lastTradeDateOrContractMonth=kwargs.get('expiry', ''),
                exchange=exchange,
                currency=currency
            )
        elif sec_type == "CASH" or sec_type == "FOREX":
            # For forex, symbol should be currency pair like "EURUSD"
            contract = Forex(symbol)
        else:
            raise ValueError(f"Unsupported security type: {sec_type}")

        # Cache the contract (with LRU eviction)
        if len(self._contract_cache) >= self._max_cache_size:
            # Remove oldest entry (simple LRU)
            self._contract_cache.pop(next(iter(self._contract_cache)))

        self._contract_cache[cache_key] = contract

        return contract

    def _smart_contract_lookup(
        self,
        symbol: str,
        sec_type: str,
        exchange: str,
        use_continuous: bool = False,
        specific_expiry: Optional[str] = None
    ) -> IBContract:
        """
        Smart contract resolution with multiple strategies.

        For futures:
        - use_continuous=True: Use continuous contract for historical data
        - use_continuous=False: Use front month contract
        - specific_expiry: Use specific contract like 'ESZ5'

        Args:
            symbol: Symbol/ticker
            sec_type: Security type
            exchange: Exchange
            use_continuous: Use continuous contract (futures only)
            specific_expiry: Specific expiry/local symbol

        Returns:
            IBKR Contract object
        """
        if sec_type.upper() == "FUT":
            if specific_expiry:
                # Use specific expiry
                contract = Future(symbol=symbol, exchange=exchange)
                contract.localSymbol = specific_expiry
                return contract
            elif use_continuous:
                # Use continuous contract
                contract = Future(symbol=symbol, exchange=exchange)
                contract.includeExpired = False
                # For continuous, IBKR uses empty lastTradeDateOrContractMonth
                return contract
            else:
                # Use front month (empty expiry will get front month)
                return Future(symbol=symbol, exchange=exchange)

        # For non-futures, use standard creation
        return self._create_contract(symbol, sec_type, exchange)

    def _contract_to_ib(self, contract: Contract) -> IBContract:
        """
        Convert internal Contract model to IB Contract.

        Args:
            contract: Internal contract model

        Returns:
            IBKR Contract object
        """
        return self._create_contract(
            symbol=contract.symbol,
            sec_type=contract.sec_type.value if isinstance(contract.sec_type, SecType) else contract.sec_type,
            exchange=contract.exchange,
            currency=contract.currency,
            expiry=contract.expiry,
            strike=contract.strike,
            right=contract.right,
            local_symbol=contract.local_symbol
        )

    def _order_to_ib(self, order: Order) -> IBOrder:
        """
        Convert internal Order model to IB Order.

        Args:
            order: Internal order model

        Returns:
            IBKR Order object
        """
        ib_order = IBOrder()
        ib_order.orderId = order.order_id or 0
        ib_order.clientId = order.client_id or self.config.client_id
        ib_order.action = order.action.value if isinstance(order.action, OrderAction) else order.action
        ib_order.totalQuantity = float(order.total_quantity)
        ib_order.orderType = order.order_type.value if isinstance(order.order_type, OrderType) else order.order_type
        ib_order.tif = order.time_in_force.value if isinstance(order.time_in_force, TimeInForce) else order.time_in_force
        ib_order.outsideRth = order.outside_rth
        ib_order.hidden = order.hidden

        if order.lmt_price:
            ib_order.lmtPrice = float(order.lmt_price)
        if order.aux_price:
            ib_order.auxPrice = float(order.aux_price)
        if order.good_after_time:
            ib_order.goodAfterTime = order.good_after_time
        if order.good_till_date:
            ib_order.goodTillDate = order.good_till_date

        return ib_order

    # ========================================================================
    # Helper Conversion Methods
    # ========================================================================

    def _ticker_to_dict(self, ticker) -> Dict[str, Any]:
        """Convert ticker to dictionary."""
        return {
            'symbol': ticker.contract.symbol if ticker.contract else None,
            'bid': float(ticker.bid) if ticker.bid and ticker.bid not in [-1, float('inf')] else None,
            'ask': float(ticker.ask) if ticker.ask and ticker.ask not in [-1, float('inf')] else None,
            'last': float(ticker.last) if ticker.last and ticker.last not in [-1, float('inf')] else None,
            'close': float(ticker.close) if ticker.close and ticker.close not in [-1, float('inf')] else None,
            'volume': int(ticker.volume) if ticker.volume and ticker.volume != -1 else None,
            'high': float(ticker.high) if ticker.high and ticker.high not in [-1, float('inf')] else None,
            'low': float(ticker.low) if ticker.low and ticker.low not in [-1, float('inf')] else None,
            'bid_size': int(ticker.bidSize) if ticker.bidSize and ticker.bidSize != -1 else None,
            'ask_size': int(ticker.askSize) if ticker.askSize and ticker.askSize != -1 else None,
            'timestamp': self._get_market_time().isoformat(),
            'market_timezone': self.config.market_timezone
        }

    def _position_to_dict(self, position) -> Dict[str, Any]:
        """Convert position to dictionary."""
        return {
            'account': position.account,
            'symbol': position.contract.symbol,
            'sec_type': position.contract.secType,
            'currency': position.contract.currency,
            'position': float(position.position),
            'avg_cost': float(position.avgCost),
            'market_price': float(position.marketPrice) if hasattr(position, 'marketPrice') and position.marketPrice else None,
            'market_value': float(position.marketValue) if hasattr(position, 'marketValue') and position.marketValue else None,
            'unrealized_pnl': float(position.unrealizedPNL) if hasattr(position, 'unrealizedPNL') and position.unrealizedPNL else None,
            'realized_pnl': float(position.realizedPNL) if hasattr(position, 'realizedPNL') and position.realizedPNL else None
        }

    def _trade_to_dict(self, trade: Trade) -> Dict[str, Any]:
        """Convert trade to dictionary."""
        return {
            'order_id': trade.order.orderId,
            'symbol': trade.contract.symbol,
            'action': trade.order.action,
            'quantity': trade.order.totalQuantity,
            'order_type': trade.order.orderType,
            'limit_price': float(trade.order.lmtPrice) if trade.order.lmtPrice else None,
            'stop_price': float(trade.order.auxPrice) if trade.order.auxPrice else None,
            'status': trade.orderStatus.status,
            'filled': trade.orderStatus.filled,
            'remaining': trade.orderStatus.remaining,
            'avg_fill_price': float(trade.orderStatus.avgFillPrice) if trade.orderStatus.avgFillPrice else None,
            'last_fill_time': trade.orderStatus.lastFillTime if hasattr(trade.orderStatus, 'lastFillTime') else None,
            'commission': float(trade.commission) if hasattr(trade, 'commission') and trade.commission else None
        }

    # ========================================================================
    # Event System
    # ========================================================================

    def register_notification_callback(self, callback: Callable) -> None:
        """
        Register callback for notifications.

        Args:
            callback: Async callable that accepts notification dict
        """
        self._notification_callbacks.append(callback)
        logger.debug(f"Registered notification callback: {callback.__name__}")

    def register_event_handler(self, event_type: str, handler: Callable) -> None:
        """
        Register event handler.

        Args:
            event_type: Event type (e.g., 'connected', 'order_status')
            handler: Callable to handle event
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
        logger.debug(f"Registered {event_type} handler: {handler.__name__}")

    async def _fire_event(self, event_type: str, data: Any) -> None:
        """
        Fire event to all registered handlers.

        Args:
            event_type: Event type
            data: Event data
        """
        # Fire to internal event handlers
        for handler in self._event_handlers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error(f"Error in {event_type} handler: {e}")

        # Send notifications for important events
        if event_type in ['order_status', 'position', 'connected', 'disconnected', 'error']:
            notification = {
                'type': f"ibkr.{event_type}",
                'data': data,
                'timestamp': self._get_local_time().isoformat()
            }

            for callback in self._notification_callbacks:
                try:
                    await callback(notification)
                except Exception as e:
                    logger.error(f"Error sending notification: {e}")

    # ========================================================================
    # Account Methods
    # ========================================================================

    async def get_account_summary(self, tags: str = "All") -> List[AccountSummary]:
        """
        Get account summary information.

        Args:
            tags: Tags to retrieve (default: "All")

        Returns:
            List of AccountSummary objects

        Raises:
            ConnectionError: If not connected
            MarketDataError: If request fails
        """
        self._ensure_connected()
        await self._rate_limiter.acquire()

        try:
            summary_items = self.ib.accountSummary()
            return [
                AccountSummary(
                    account=item.account,
                    tag=item.tag,
                    value=item.value,
                    currency=item.currency
                )
                for item in summary_items
            ]
        except Exception as e:
            logger.error(f"Failed to get account summary: {e}")
            raise MarketDataError(f"Account summary error: {e}")

    async def get_account_values(self) -> List[Dict[str, Any]]:
        """
        Get account values.

        Returns:
            List of account value dictionaries

        Raises:
            ConnectionError: If not connected
            MarketDataError: If request fails
        """
        self._ensure_connected()
        await self._rate_limiter.acquire()

        try:
            account_values = self.ib.accountValues()
            return [
                {
                    'account': item.account,
                    'tag': item.tag,
                    'value': item.value,
                    'currency': item.currency
                }
                for item in account_values
            ]
        except Exception as e:
            logger.error(f"Failed to get account values: {e}")
            raise MarketDataError(f"Account values error: {e}")

    async def get_positions(self) -> List[Position]:
        """
        Get all positions.

        Returns:
            List of Position objects

        Raises:
            ConnectionError: If not connected
            MarketDataError: If request fails
        """
        self._ensure_connected()
        await self._rate_limiter.acquire()

        try:
            positions = self.ib.positions()
            result = []

            for pos in positions:
                contract = Contract(
                    symbol=pos.contract.symbol,
                    sec_type=SecType(pos.contract.secType),
                    exchange=pos.contract.exchange,
                    currency=pos.contract.currency
                )

                position = Position(
                    account=pos.account,
                    contract=contract,
                    position=Decimal(str(pos.position)),
                    avg_cost=Decimal(str(pos.avgCost))
                )
                result.append(position)

            return result
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            raise MarketDataError(f"Positions error: {e}")

    # ========================================================================
    # Market Data Methods (Internal - use Contract objects)
    # ========================================================================

    async def _get_realtime_price_internal(
        self,
        contract: Contract,
        snapshot: bool = True
    ) -> Optional[TickData]:
        """
        Get real-time market data.

        Args:
            contract: Contract to get price for
            snapshot: Get snapshot (vs streaming)

        Returns:
            TickData object or None

        Raises:
            ConnectionError: If not connected
            MarketDataError: If request fails
            DataError: If no data available (fast failover)
        """
        self._ensure_connected()
        await self._rate_limiter.acquire()

        try:
            ib_contract = self._contract_to_ib(contract)

            # Qualify contract
            qualified_contracts = await self.ib.qualifyContractsAsync(ib_contract)
            if not qualified_contracts:
                raise MarketDataError(f"Could not qualify contract: {contract.symbol}")

            ib_contract = qualified_contracts[0]

            # Request market data snapshot
            ticker = self.ib.reqMktData(ib_contract, '', snapshot, False)

            # Wait for data with timeout
            await asyncio.sleep(self.config.data_timeout)

            # Cancel market data if snapshot
            if snapshot:
                self.ib.cancelMktData(ib_contract)

            # Check if we got valid data
            if not ticker or not ticker.last or ticker.last in [-1, float('inf')]:
                raise DataError(f"No market data available for {contract.symbol}")

            # Build TickData response
            price = None
            size = None

            if ticker.last and str(ticker.last).lower() not in ['nan', 'inf', '-inf']:
                try:
                    price_val = Decimal(str(ticker.last))
                    if price_val.is_finite():
                        price = price_val
                except Exception:
                    pass

            if hasattr(ticker, 'lastSize') and ticker.lastSize is not None:
                try:
                    size_val = float(ticker.lastSize)
                    if size_val == size_val and size_val >= 0:  # NaN check
                        size = int(size_val)
                except Exception:
                    pass

            return TickData(
                symbol=contract.symbol,
                tick_type=1,  # Last price
                price=price,
                size=size
            )

        except DataError:
            # Re-raise data errors for fast failover
            raise
        except Exception as e:
            logger.error(f"Failed to get market data: {e}")
            raise MarketDataError(f"Market data error: {e}")

    async def _get_historical_data_internal(
        self,
        contract: Contract,
        duration: str = "1 D",
        bar_size: str = "1 min",
        what_to_show: str = "TRADES",
        use_rth: bool = True,
        use_continuous: bool = False,
        specific_expiry: Optional[str] = None
    ) -> List[BarData]:
        """
        Get historical market data.

        For futures:
        - use_continuous=True: Use continuous contract
        - specific_expiry: Use specific contract like 'ESZ5'

        Args:
            contract: Contract to get data for
            duration: Duration string (e.g., "1 D", "1 W", "1 M")
            bar_size: Bar size (e.g., "1 min", "5 mins", "1 hour")
            what_to_show: Data type ("TRADES", "MIDPOINT", "BID", "ASK")
            use_rth: Use regular trading hours only
            use_continuous: Use continuous contract (futures only)
            specific_expiry: Specific expiry (futures only)

        Returns:
            List of BarData objects

        Raises:
            ConnectionError: If not connected
            MarketDataError: If request fails
        """
        self._ensure_connected()
        await self._rate_limiter.acquire()

        try:
            # Smart contract lookup for futures
            if contract.sec_type == SecType.FUTURE:
                ib_contract = self._smart_contract_lookup(
                    contract.symbol,
                    "FUT",
                    contract.exchange,
                    use_continuous=use_continuous,
                    specific_expiry=specific_expiry
                )
            else:
                ib_contract = self._contract_to_ib(contract)

            # Qualify contract
            qualified_contracts = await self.ib.qualifyContractsAsync(ib_contract)
            if not qualified_contracts:
                raise MarketDataError(f"Could not qualify contract: {contract.symbol}")

            ib_contract = qualified_contracts[0]

            # Request historical data
            bars = await self.ib.reqHistoricalDataAsync(
                contract=ib_contract,
                endDateTime='',
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=use_rth
            )

            return [
                BarData(
                    date=bar.date,
                    open=Decimal(str(bar.open)),
                    high=Decimal(str(bar.high)),
                    low=Decimal(str(bar.low)),
                    close=Decimal(str(bar.close)),
                    volume=bar.volume,
                    wap=Decimal(str(bar.wap)) if hasattr(bar, 'wap') and bar.wap else None,
                    count=bar.barCount if hasattr(bar, 'barCount') else None
                )
                for bar in bars
            ]

        except Exception as e:
            logger.error(f"Failed to get historical data: {e}")
            raise MarketDataError(f"Historical data error: {e}")

    # ========================================================================
    # Order Methods (Internal - use Contract/Order objects)
    # ========================================================================

    async def _place_order_internal(self, contract: Contract, order: Order) -> Trade:
        """
        Place an order.

        Args:
            contract: Contract to trade
            order: Order details

        Returns:
            Trade object

        Raises:
            ConnectionError: If not connected
            OrderError: If order placement fails
        """
        self._ensure_connected()
        await self._rate_limiter.acquire()

        try:
            ib_contract = self._contract_to_ib(contract)
            ib_order = self._order_to_ib(order)

            # Qualify contract if needed
            qualified_contracts = await self.ib.qualifyContractsAsync(ib_contract)
            if not qualified_contracts:
                raise OrderError(f"Could not qualify contract: {contract.symbol}")

            ib_contract = qualified_contracts[0]

            # Place order
            trade = self.ib.placeOrder(ib_contract, ib_order)

            logger.info(f"Order placed: {trade.order.orderId} for {contract.symbol}")
            await self._fire_event('order_status', self._trade_to_dict(trade))

            return trade

        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            raise OrderError(f"Order placement error: {e}")

    async def cancel_order(self, order_id: int) -> bool:
        """
        Cancel an order.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if cancelled successfully

        Raises:
            ConnectionError: If not connected
            OrderError: If cancellation fails
        """
        self._ensure_connected()
        await self._rate_limiter.acquire()

        try:
            # Get open trades to find the order
            open_trades = self.ib.openTrades()

            # Find matching order
            target_order = None
            for trade in open_trades:
                if trade.order.orderId == order_id:
                    target_order = trade.order
                    break

            if target_order is None:
                logger.error(f"Order {order_id} not found in open trades")
                raise OrderError(f"Order {order_id} not found")

            # Cancel the order
            self.ib.cancelOrder(target_order)
            logger.info(f"Order cancelled: {order_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise OrderError(f"Order cancellation error: {e}")

    async def get_open_orders(self) -> List[Trade]:
        """
        Get all open orders.

        Returns:
            List of Trade objects

        Raises:
            ConnectionError: If not connected
            OrderError: If request fails
        """
        self._ensure_connected()
        await self._rate_limiter.acquire()

        try:
            return self.ib.openTrades()
        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            raise OrderError(f"Open orders error: {e}")

    # ========================================================================
    # Wrapper Methods for Tool Functions
    # ========================================================================
    # These methods provide simple signatures that match server.py expectations
    # and delegate to the tool functions in tools/*.py

    # --- Signature-Fixed Wrappers ---

    async def get_realtime_price(
        self,
        symbol: str,
        sec_type: str = "STK",
        exchange: str = "SMART"
    ) -> Dict[str, Any]:
        """
        Get real-time price (wrapper that delegates to market_data tool).

        Args:
            symbol: Trading symbol
            sec_type: Security type (STK, OPT, FUT, etc.)
            exchange: Exchange (default: SMART)

        Returns:
            Dict with price data
        """
        from .tools import market_data
        return await market_data.get_realtime_price(self, symbol, sec_type, exchange)

    async def get_historical_data(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "1 hour",
        sec_type: str = "STK",
        exchange: str = "SMART",
        page: int = 1,
        page_size: int = 100
    ) -> Dict[str, Any]:
        """
        Get historical data with pagination (wrapper that delegates to market_data tool).

        Args:
            symbol: Trading symbol
            duration: Duration string (e.g., "1 D", "1 W")
            bar_size: Bar size (e.g., "1 min", "1 hour")
            sec_type: Security type
            exchange: Exchange
            page: Page number for pagination
            page_size: Number of bars per page

        Returns:
            Dict with historical data
        """
        from .tools import market_data
        return await market_data.get_historical_data(
            self, symbol, duration, bar_size, sec_type, exchange, page, page_size
        )

    async def place_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        sec_type: str = "STK",
        exchange: str = "SMART"
    ) -> Dict[str, Any]:
        """
        Place an order (wrapper that delegates to orders tool).

        Args:
            symbol: Trading symbol
            action: Order action (BUY/SELL)
            quantity: Order quantity
            order_type: Order type (MKT, LMT, STP, etc.)
            limit_price: Limit price (for LMT orders)
            stop_price: Stop price (for STP orders)
            sec_type: Security type
            exchange: Exchange

        Returns:
            Dict with order result
        """
        from .tools import orders
        return await orders.place_order(
            self, symbol, action, quantity, order_type,
            limit_price, stop_price, sec_type, exchange
        )

    # --- Market Data Methods ---

    async def search_symbols(self, pattern: str) -> Dict[str, Any]:
        """Search for tradable instruments matching a pattern."""
        from .tools import market_data
        return await market_data.search_symbols(self, pattern)

    async def get_news(
        self,
        symbol: str,
        sec_type: str = "STK",
        exchange: str = "SMART"
    ) -> Dict[str, Any]:
        """Get news for a symbol."""
        from .tools import market_data
        return await market_data.get_news(self, symbol, sec_type, exchange)

    async def get_order_book(
        self,
        symbol: str,
        depth: int = 5
    ) -> Dict[str, Any]:
        """Get order book (Level 2) data."""
        from .tools import market_data
        return await market_data.get_order_book(self, symbol, depth)

    async def calculate_slippage(self, order_id: int) -> Dict[str, Any]:
        """Calculate slippage for an executed order."""
        from .tools import market_data
        return await market_data.calculate_slippage(self, order_id)

    # --- Account Methods ---

    async def analyze_portfolio_allocation(self) -> Dict[str, Any]:
        """Analyze portfolio allocation and diversification."""
        from .tools import account
        return await account.analyze_portfolio_allocation(self)

    async def calculate_rebalancing_orders(
        self,
        target_allocation: Dict[str, float],
        tolerance: float = 0.05
    ) -> Dict[str, Any]:
        """Calculate orders needed to rebalance portfolio."""
        from .tools import account
        return await account.calculate_rebalancing_orders(
            self, target_allocation, tolerance
        )

    async def execute_rebalancing(
        self,
        rebalancing_orders: List[Dict[str, Any]],
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """Execute portfolio rebalancing orders."""
        from .tools import account
        return await account.execute_rebalancing(self, rebalancing_orders, dry_run)

    # --- Advanced Order Methods ---

    async def place_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        entry_price: float,
        profit_target: float,
        stop_loss: float,
        sec_type: str = "STK",
        exchange: str = "SMART"
    ) -> Dict[str, Any]:
        """Place a bracket order (entry + take profit + stop loss)."""
        from .tools import orders_advanced
        return await orders_advanced.place_bracket_order(
            self, symbol, action, quantity, entry_price,
            profit_target, stop_loss, sec_type, exchange
        )

    async def place_trailing_stop(
        self,
        symbol: str,
        action: str,
        quantity: int,
        trail_amount: float,
        trail_percent: Optional[float] = None,
        sec_type: str = "STK",
        exchange: str = "SMART"
    ) -> Dict[str, Any]:
        """Place a trailing stop order."""
        from .tools import orders_advanced
        return await orders_advanced.place_trailing_stop(
            self, symbol, action, quantity, trail_amount,
            trail_percent, sec_type, exchange
        )

    async def place_one_cancels_all(
        self,
        symbol: str,
        action: str,
        quantity: int,
        order_configs: List[Dict[str, Any]],
        sec_type: str = "STK",
        exchange: str = "SMART"
    ) -> Dict[str, Any]:
        """Place a one-cancels-all (OCA) order group."""
        from .tools import orders_advanced
        return await orders_advanced.place_one_cancels_all(
            self, symbol, action, quantity, order_configs, sec_type, exchange
        )

    async def place_algo_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        algo_strategy: str,
        algo_params: Dict[str, Any],
        sec_type: str = "STK",
        exchange: str = "SMART"
    ) -> Dict[str, Any]:
        """Place an algorithmic order (TWAP, VWAP, etc.)."""
        from .tools import orders_advanced
        return await orders_advanced.place_algo_order(
            self, symbol, action, quantity, algo_strategy,
            algo_params, sec_type, exchange
        )

    # --- Options Methods ---

    async def get_option_chain(
        self,
        symbol: str,
        exchange: str = "SMART"
    ) -> Dict[str, Any]:
        """Get option chain for a symbol."""
        from .tools import options
        return await options.get_option_chain(self, symbol, exchange)

    async def analyze_option_spread(
        self,
        symbol: str,
        strategy: str,
        expiry: str,
        strikes: List[float],
        exchange: str = "SMART"
    ) -> Dict[str, Any]:
        """Analyze option spread strategies."""
        from .tools import options
        return await options.analyze_option_spread(
            self, symbol, strategy, expiry, strikes, exchange
        )

    # --- Futures Methods ---

    async def get_futures_chain(
        self,
        underlying: str,
        exchange: str = "CME"
    ) -> Dict[str, Any]:
        """Get futures chain for an underlying."""
        from .tools import futures
        return await futures.get_futures_chain(self, underlying, exchange)

    async def detect_rollover_needed(
        self,
        symbol: str,
        exchange: str = "CME",
        days_before: int = 5
    ) -> Dict[str, Any]:
        """Detect if futures contract rollover is needed."""
        from .tools import futures
        return await futures.detect_rollover_needed(
            self, symbol, exchange, days_before
        )

    async def get_contract_by_conid(self, con_id: int) -> Dict[str, Any]:
        """Get contract details by contract ID."""
        from .tools import futures
        return await futures.get_contract_by_conid(self, con_id)

    # --- Scanner Methods ---

    async def scan_market(
        self,
        scan_code: str,
        location: str = "STK.US.MAJOR",
        instrument: str = "STK",
        num_rows: int = 50
    ) -> Dict[str, Any]:
        """Run a market scanner."""
        from .tools import scanners
        return await scanners.scan_market(
            self, scan_code, location, instrument, num_rows
        )

    async def create_custom_scanner(
        self,
        criteria: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a custom market scanner."""
        from .tools import scanners
        return await scanners.create_custom_scanner(self, criteria)

    async def scan_options_volume(
        self,
        underlying: str,
        min_volume: int = 1000,
        exchange: str = "SMART"
    ) -> Dict[str, Any]:
        """Scan for high-volume options."""
        from .tools import scanners
        return await scanners.scan_options_volume(
            self, underlying, min_volume, exchange
        )

    # --- Risk Management Methods ---

    async def calculate_position_size(
        self,
        symbol: str,
        risk_amount: float,
        stop_loss_price: float,
        entry_price: float,
        sec_type: str = "STK",
        exchange: str = "SMART"
    ) -> Dict[str, Any]:
        """Calculate position size based on risk parameters."""
        from .tools import risk
        return await risk.calculate_position_size(
            self, symbol, risk_amount, stop_loss_price,
            entry_price, sec_type, exchange
        )

    async def check_risk_limits(self) -> Dict[str, Any]:
        """Check if portfolio is within risk limits."""
        from .tools import risk
        return await risk.check_risk_limits(self)

    async def calculate_var(
        self,
        confidence_level: float = 0.95,
        time_horizon: int = 1
    ) -> Dict[str, Any]:
        """Calculate Value at Risk (VaR) for portfolio."""
        from .tools import risk
        return await risk.calculate_var(self, confidence_level, time_horizon)

    async def set_stop_loss_orders(
        self,
        stop_loss_pct: float = 0.02,
        trailing: bool = False
    ) -> Dict[str, Any]:
        """Set stop loss orders for all positions."""
        from .tools import risk
        return await risk.set_stop_loss_orders(self, stop_loss_pct, trailing)
