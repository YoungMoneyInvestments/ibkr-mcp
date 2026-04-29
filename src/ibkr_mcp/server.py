"""
Main IBKR MCP Server implementation using FastMCP.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP
from loguru import logger

from .config import ServerConfig
from .client import IBKRClient
from .models import SecType, OrderAction, OrderType, AlgoStrategy
from .utils.circuit_breaker import TradingCircuitBreaker
from .exceptions import CircuitBreakerError


class IBKRMCPServer:
    """IBKR MCP Server - Full-featured Interactive Brokers integration."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.client = IBKRClient(config.ibkr)
        self.circuit_breaker = TradingCircuitBreaker(
            max_loss_per_minute=config.risk.max_loss_per_minute,
            max_trades_per_minute=config.risk.max_trades_per_minute,
            max_daily_loss=config.risk.max_daily_loss,
            max_position_size=config.risk.max_position_size,
        )
        # Wire circuit breaker into fill callbacks for P&L tracking
        self.client.register_event_handler('order_status', self._on_order_status)
        self.mcp = FastMCP(
            "IBKR MCP Server",
            version="1.0.0",
        )
        self._setup_tools()

    def _estimate_trade_value(
        self,
        quantity: int,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        entry_price: Optional[float] = None,
    ) -> float:
        """Estimate dollar value of a trade for circuit breaker checks."""
        price = limit_price or stop_price or entry_price
        if price and quantity:
            return abs(quantity * price)
        return 0.0

    def _check_circuit_breaker(self, trade_value: float) -> Optional[Dict[str, Any]]:
        """Check circuit breaker before trade. Returns error dict if blocked, None if OK."""
        allowed, reason = self.circuit_breaker.check_trade(trade_value)
        if not allowed:
            return {
                "success": False,
                "error": f"Circuit breaker: {reason}",
                "timestamp": datetime.now().isoformat(),
            }
        return None

    def _on_order_status(self, event_data: Dict[str, Any]) -> None:
        """Track order fills for circuit breaker P&L monitoring."""
        try:
            status = event_data.get('status', '')
            if status == 'Filled':
                filled = event_data.get('filled', 0)
                avg_price = event_data.get('avg_fill_price', 0)
                action = event_data.get('action', '')
                commission = event_data.get('commission')

                # Record commission as realized cost
                if commission:
                    self.circuit_breaker.record_pnl(-abs(commission))
                    logger.debug(
                        f"Circuit breaker recorded commission: -${abs(commission):.2f}"
                    )

                logger.info(
                    f"Circuit breaker tracked fill: {action} {filled} @ ${avg_price}"
                )
        except Exception as e:
            logger.error(f"Error in circuit breaker fill handler: {e}")

    def _setup_tools(self) -> None:
        """Register all MCP tools."""

        # =====================================================================
        # Connection Tools
        # =====================================================================

        @self.mcp.tool()
        async def connection_status() -> Dict[str, Any]:
            """Check IBKR connection status."""
            return {
                "success": True,
                "data": {
                    "connected": self.client.is_connected(),
                    "host": self.config.ibkr.host,
                    "port": self.config.ibkr.port,
                    "client_id": self.config.ibkr.client_id,
                    "readonly": self.config.ibkr.readonly,
                },
                "timestamp": datetime.now().isoformat(),
            }

        @self.mcp.tool()
        async def reconnect() -> Dict[str, Any]:
            """Reconnect to IBKR."""
            try:
                success = await self.client.reconnect()
                return {
                    "success": success,
                    "data": {"reconnected": success},
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Reconnection error: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                }

        # =====================================================================
        # Account Tools
        # =====================================================================

        @self.mcp.tool()
        async def get_account_summary() -> Dict[str, Any]:
            """Get account summary including balances, buying power, and margin."""
            try:
                summary = await self.client.get_account_summary()
                return {
                    "success": True,
                    "data": summary,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Account summary error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def get_positions() -> Dict[str, Any]:
            """Get all current positions with P&L."""
            try:
                positions = await self.client.get_positions()
                return {
                    "success": True,
                    "data": positions,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Positions error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def analyze_portfolio_allocation() -> Dict[str, Any]:
            """Analyze portfolio allocation by asset class, symbol, and currency."""
            try:
                allocation = await self.client.analyze_portfolio_allocation()
                return {
                    "success": True,
                    "data": allocation,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Portfolio analysis error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Market Data Tools
        # =====================================================================

        @self.mcp.tool()
        async def get_realtime_price(
            symbol: str,
            sec_type: str = "STK",
            exchange: str = "SMART",
        ) -> Dict[str, Any]:
            """Get real-time price for a symbol."""
            try:
                price_data = await self.client.get_realtime_price(symbol, sec_type, exchange)
                return {
                    "success": True,
                    "data": price_data,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Price error for {symbol}: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def get_historical_data(
            symbol: str,
            duration: str = "1 D",
            bar_size: str = "1 hour",
            sec_type: str = "STK",
            exchange: str = "SMART",
            page: int = 1,
            page_size: int = 100,
        ) -> Dict[str, Any]:
            """Get historical price data with pagination."""
            try:
                data = await self.client.get_historical_data(
                    symbol=symbol,
                    duration=duration,
                    bar_size=bar_size,
                    sec_type=sec_type,
                    exchange=exchange,
                    page=page,
                    page_size=page_size,
                )
                return {
                    "success": True,
                    "data": data,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Historical data error for {symbol}: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def search_symbols(pattern: str) -> Dict[str, Any]:
            """Search for tradable instruments matching a pattern."""
            try:
                results = await self.client.search_symbols(pattern)
                return {
                    "success": True,
                    "data": results,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Symbol search error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Order Tools
        # =====================================================================

        @self.mcp.tool()
        async def place_order(
            symbol: str,
            action: str,
            quantity: int,
            order_type: str = "MKT",
            limit_price: Optional[float] = None,
            stop_price: Optional[float] = None,
            sec_type: str = "STK",
            exchange: str = "SMART",
        ) -> Dict[str, Any]:
            """Place a trading order (market, limit, or stop)."""
            if self.config.ibkr.readonly:
                return {"success": False, "error": "Read-only mode - trading disabled"}

            trade_value = self._estimate_trade_value(quantity, limit_price=limit_price, stop_price=stop_price)
            blocked = self._check_circuit_breaker(trade_value)
            if blocked:
                return blocked

            try:
                result = await self.client.place_order(
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                    order_type=order_type,
                    limit_price=limit_price,
                    stop_price=stop_price,
                    sec_type=sec_type,
                    exchange=exchange,
                )
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Order error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def place_bracket_order(
            symbol: str,
            action: str,
            quantity: int,
            entry_price: float,
            profit_target: float,
            stop_loss: float,
            sec_type: str = "STK",
            exchange: str = "SMART",
        ) -> Dict[str, Any]:
            """Place a bracket order (entry + take profit + stop loss)."""
            if self.config.ibkr.readonly:
                return {"success": False, "error": "Read-only mode - trading disabled"}

            trade_value = self._estimate_trade_value(quantity, entry_price=entry_price)
            blocked = self._check_circuit_breaker(trade_value)
            if blocked:
                return blocked

            try:
                result = await self.client.place_bracket_order(
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                    entry_price=entry_price,
                    profit_target=profit_target,
                    stop_loss=stop_loss,
                    sec_type=sec_type,
                    exchange=exchange,
                )
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Bracket order error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def cancel_order(order_id: int) -> Dict[str, Any]:
            """Cancel an open order."""
            try:
                success = await self.client.cancel_order(order_id)
                return {
                    "success": success,
                    "data": {"order_id": order_id, "cancelled": success},
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Cancel order error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def get_open_orders() -> Dict[str, Any]:
            """Get all open orders."""
            try:
                orders = await self.client.get_open_orders()
                return {
                    "success": True,
                    "data": orders,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Open orders error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Options Tools
        # =====================================================================

        @self.mcp.tool()
        async def get_option_chain(
            symbol: str,
            exchange: str = "SMART",
        ) -> Dict[str, Any]:
            """Get option chain with Greeks for a symbol."""
            try:
                chain = await self.client.get_option_chain(symbol, exchange)
                return {
                    "success": True,
                    "data": chain,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Option chain error for {symbol}: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def analyze_option_spread(
            symbol: str,
            strategy: str,
            strike1: float,
            strike2: Optional[float] = None,
            expiry: Optional[str] = None,
            quantity: int = 1,
        ) -> Dict[str, Any]:
            """Analyze option spread strategies (bull_call, bear_put, straddle, etc.)."""
            try:
                analysis = await self.client.analyze_option_spread(
                    symbol=symbol,
                    strategy=strategy,
                    strike1=strike1,
                    strike2=strike2,
                    expiry=expiry,
                    quantity=quantity,
                )
                return {
                    "success": True,
                    "data": analysis,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Option spread analysis error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Futures Tools
        # =====================================================================

        @self.mcp.tool()
        async def get_futures_chain(
            underlying: str,
            exchange: str = "CME",
        ) -> Dict[str, Any]:
            """Get all available futures contracts for an underlying."""
            try:
                chain = await self.client.get_futures_chain(underlying, exchange)
                return {
                    "success": True,
                    "data": chain,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Futures chain error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def detect_rollover_needed(
            symbol: str,
            exchange: str = "CME",
            days_before: int = 5,
        ) -> Dict[str, Any]:
            """Check if futures contract rollover is needed."""
            try:
                result = await self.client.detect_rollover_needed(symbol, exchange, days_before)
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Rollover detection error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Scanner Tools
        # =====================================================================

        @self.mcp.tool()
        async def scan_market(
            scan_code: str,
            location: str = "STK.US.MAJOR",
            instrument: str = "STK",
            num_rows: int = 50,
        ) -> Dict[str, Any]:
            """Run a market scanner (TOP_PERC_GAIN, MOST_ACTIVE, etc.)."""
            try:
                results = await self.client.scan_market(scan_code, location, instrument, num_rows)
                return {
                    "success": True,
                    "data": results,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Market scan error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Algorithmic Order Tools (Convenience Wrappers)
        # =====================================================================

        @self.mcp.tool()
        async def place_twap_order(
            symbol: str,
            action: str,
            quantity: int,
            start_time: str = "",
            end_time: str = "",
            strategy_type: str = "Marketable",
            sec_type: str = "STK",
            exchange: str = "SMART",
        ) -> Dict[str, Any]:
            """Place a TWAP (Time-Weighted Average Price) algorithmic order."""
            if self.config.ibkr.readonly:
                return {"success": False, "error": "Read-only mode - trading disabled"}

            blocked = self._check_circuit_breaker(0.0)
            if blocked:
                return blocked

            try:
                from .tools.orders_advanced import create_twap_params, place_algo_order

                # Create TWAP parameters
                algo_params = create_twap_params(
                    strategy_type=strategy_type,
                    start_time=start_time,
                    end_time=end_time,
                )

                # Place the algo order
                result = await place_algo_order(
                    client=self.client,
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                    algo_strategy="Twap",
                    algo_params=algo_params,
                    sec_type=sec_type,
                    exchange=exchange,
                )

                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"TWAP order error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def place_vwap_order(
            symbol: str,
            action: str,
            quantity: int,
            max_pct_vol: float = 0.1,
            start_time: str = "",
            end_time: str = "",
            no_take_liq: bool = False,
            sec_type: str = "STK",
            exchange: str = "SMART",
        ) -> Dict[str, Any]:
            """Place a VWAP (Volume-Weighted Average Price) algorithmic order."""
            if self.config.ibkr.readonly:
                return {"success": False, "error": "Read-only mode - trading disabled"}

            blocked = self._check_circuit_breaker(0.0)
            if blocked:
                return blocked

            try:
                from .tools.orders_advanced import create_vwap_params, place_algo_order

                # Create VWAP parameters
                algo_params = create_vwap_params(
                    max_pct_vol=max_pct_vol,
                    start_time=start_time,
                    end_time=end_time,
                    no_take_liq=no_take_liq,
                )

                # Place the algo order
                result = await place_algo_order(
                    client=self.client,
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                    algo_strategy="Vwap",
                    algo_params=algo_params,
                    sec_type=sec_type,
                    exchange=exchange,
                )

                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"VWAP order error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def place_arrival_price_order(
            symbol: str,
            action: str,
            quantity: int,
            max_pct_vol: float = 0.1,
            risk_aversion: str = "Neutral",
            start_time: str = "",
            end_time: str = "",
            force_completion: bool = False,
            sec_type: str = "STK",
            exchange: str = "SMART",
        ) -> Dict[str, Any]:
            """Place an Arrival Price algorithmic order."""
            if self.config.ibkr.readonly:
                return {"success": False, "error": "Read-only mode - trading disabled"}

            blocked = self._check_circuit_breaker(0.0)
            if blocked:
                return blocked

            try:
                from .tools.orders_advanced import create_arrival_price_params, place_algo_order

                # Create Arrival Price parameters
                algo_params = create_arrival_price_params(
                    max_pct_vol=max_pct_vol,
                    risk_aversion=risk_aversion,
                    start_time=start_time,
                    end_time=end_time,
                    force_completion=force_completion,
                )

                # Place the algo order
                result = await place_algo_order(
                    client=self.client,
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                    algo_strategy="ArrivalPx",
                    algo_params=algo_params,
                    sec_type=sec_type,
                    exchange=exchange,
                )

                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Arrival Price order error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def place_adaptive_order(
            symbol: str,
            action: str,
            quantity: int,
            priority: str = "Normal",
            sec_type: str = "STK",
            exchange: str = "SMART",
        ) -> Dict[str, Any]:
            """Place an IB Adaptive algorithmic order."""
            if self.config.ibkr.readonly:
                return {"success": False, "error": "Read-only mode - trading disabled"}

            blocked = self._check_circuit_breaker(0.0)
            if blocked:
                return blocked

            try:
                from .tools.orders_advanced import create_adaptive_params, place_algo_order

                # Create Adaptive parameters
                algo_params = create_adaptive_params(priority=priority)

                # Place the algo order
                result = await place_algo_order(
                    client=self.client,
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                    algo_strategy="Adaptive",
                    algo_params=algo_params,
                    sec_type=sec_type,
                    exchange=exchange,
                )

                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Adaptive order error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Risk Management Tools
        # =====================================================================

        @self.mcp.tool()
        async def calculate_position_size(
            symbol: str,
            risk_amount: float,
            stop_loss: float,
            entry_price: Optional[float] = None,
            method: str = "fixed_risk",
        ) -> Dict[str, Any]:
            """Calculate optimal position size based on risk parameters."""
            try:
                result = await self.client.calculate_position_size(
                    symbol=symbol,
                    risk_amount=risk_amount,
                    stop_loss=stop_loss,
                    entry_price=entry_price,
                    method=method,
                )
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Position sizing error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def check_risk_limits() -> Dict[str, Any]:
            """Check current portfolio against risk limits."""
            try:
                result = await self.client.check_risk_limits()
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Risk check error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def calculate_var(
            confidence_level: float = 0.95,
            time_horizon: int = 1,
        ) -> Dict[str, Any]:
            """Calculate Value at Risk for the portfolio."""
            try:
                result = await self.client.calculate_var(confidence_level, time_horizon)
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"VaR calculation error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Additional Account Tools
        # =====================================================================

        @self.mcp.tool()
        async def calculate_rebalancing_orders(
            target_allocations: Dict[str, float],
            rebalance_threshold: float = 0.05,
            use_cash: bool = True,
        ) -> Dict[str, Any]:
            """Calculate trades needed to rebalance portfolio to target allocations."""
            try:
                result = await self.client.calculate_rebalancing_orders(
                    target_allocations=target_allocations,
                    rebalance_threshold=rebalance_threshold,
                    use_cash=use_cash,
                )
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Rebalancing calculation error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def execute_rebalancing(
            rebalancing_plan: Dict[str, Any],
            order_type: str = "MARKET",
            execute_sells_first: bool = True,
        ) -> Dict[str, Any]:
            """Execute rebalancing trades from a rebalancing plan."""
            if self.config.ibkr.readonly:
                return {"success": False, "error": "Read-only mode - trading disabled"}

            blocked = self._check_circuit_breaker(0.0)
            if blocked:
                return blocked

            try:
                result = await self.client.execute_rebalancing(
                    rebalancing_plan=rebalancing_plan,
                    order_type=order_type,
                    execute_sells_first=execute_sells_first,
                )
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Rebalancing execution error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Additional Market Data Tools
        # =====================================================================

        @self.mcp.tool()
        async def get_news(
            symbol: str,
            sec_type: str = "STK",
            exchange: str = "SMART",
        ) -> Dict[str, Any]:
            """Get news bulletins for a symbol."""
            try:
                result = await self.client.get_news(symbol, sec_type, exchange)
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"News retrieval error for {symbol}: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def get_order_book(
            symbol: str,
            depth: int = 5,
        ) -> Dict[str, Any]:
            """Get Level 2 order book data (market depth)."""
            try:
                result = await self.client.get_order_book(symbol, depth)
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Order book error for {symbol}: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def calculate_slippage(order_id: int) -> Dict[str, Any]:
            """Calculate execution slippage for an order."""
            try:
                result = await self.client.calculate_slippage(order_id)
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Slippage calculation error for order {order_id}: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Additional Advanced Order Tools
        # =====================================================================

        @self.mcp.tool()
        async def place_trailing_stop(
            symbol: str,
            action: str,
            quantity: int,
            trail_amount: Optional[float] = None,
            trail_percent: Optional[float] = None,
            sec_type: str = "STK",
            exchange: str = "SMART",
        ) -> Dict[str, Any]:
            """Place a trailing stop order."""
            if self.config.ibkr.readonly:
                return {"success": False, "error": "Read-only mode - trading disabled"}

            blocked = self._check_circuit_breaker(0.0)
            if blocked:
                return blocked

            try:
                result = await self.client.place_trailing_stop(
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                    trail_amount=trail_amount,
                    trail_percent=trail_percent,
                    sec_type=sec_type,
                    exchange=exchange,
                )
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Trailing stop order error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def place_one_cancels_all(
            orders: List[Dict[str, Any]],
            oca_group: str,
            oca_type: int = 1,
        ) -> Dict[str, Any]:
            """Place One-Cancels-All (OCA) order group."""
            if self.config.ibkr.readonly:
                return {"success": False, "error": "Read-only mode - trading disabled"}

            blocked = self._check_circuit_breaker(0.0)
            if blocked:
                return blocked

            try:
                result = await self.client.place_one_cancels_all(
                    orders=orders,
                    oca_group=oca_group,
                    oca_type=oca_type,
                )
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"OCA order error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def place_algo_order(
            symbol: str,
            action: str,
            quantity: int,
            algo_strategy: str,
            algo_params: Dict[str, str],
            sec_type: str = "STK",
            exchange: str = "SMART",
        ) -> Dict[str, Any]:
            """Place an algorithmic order using IBKR's algo strategies."""
            if self.config.ibkr.readonly:
                return {"success": False, "error": "Read-only mode - trading disabled"}

            blocked = self._check_circuit_breaker(0.0)
            if blocked:
                return blocked

            try:
                result = await self.client.place_algo_order(
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                    algo_strategy=algo_strategy,
                    algo_params=algo_params,
                    sec_type=sec_type,
                    exchange=exchange,
                )
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Algo order error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Additional Futures Tools
        # =====================================================================

        @self.mcp.tool()
        async def get_contract_by_conid(con_id: int) -> Dict[str, Any]:
            """Get contract details by contract ID."""
            try:
                result = await self.client.get_contract_by_conid(con_id)
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Contract lookup error for conId {con_id}: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Additional Scanner Tools
        # =====================================================================

        @self.mcp.tool()
        async def create_custom_scanner(criteria: Dict[str, Any]) -> Dict[str, Any]:
            """Create custom scanner with specific criteria."""
            try:
                result = await self.client.create_custom_scanner(criteria)
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Custom scanner error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def scan_options_volume(
            underlying: Optional[str] = None,
            min_volume: int = 1000,
            min_open_interest: int = 100,
        ) -> Dict[str, Any]:
            """Scan for unusual options activity."""
            try:
                result = await self.client.scan_options_volume(
                    underlying=underlying,
                    min_volume=min_volume,
                    min_open_interest=min_open_interest,
                )
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Options volume scan error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Additional Risk Management Tools
        # =====================================================================

        @self.mcp.tool()
        async def set_stop_loss_orders(
            trail_percent: Optional[float] = None,
            trail_amount: Optional[float] = None,
        ) -> Dict[str, Any]:
            """Automatically set stop loss orders for all positions."""
            if self.config.ibkr.readonly:
                return {"success": False, "error": "Read-only mode - trading disabled"}

            blocked = self._check_circuit_breaker(0.0)
            if blocked:
                return blocked

            try:
                result = await self.client.set_stop_loss_orders(
                    trail_percent=trail_percent,
                    trail_amount=trail_amount,
                )
                return {
                    "success": True,
                    "data": result,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Stop loss order error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        # =====================================================================
        # Circuit Breaker Tools
        # =====================================================================

        @self.mcp.tool()
        async def circuit_breaker_status() -> Dict[str, Any]:
            """Get circuit breaker status including trip state, daily P&L, and utilization."""
            try:
                status = self.circuit_breaker.get_status()
                return {
                    "success": True,
                    "data": status,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Circuit breaker status error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

        @self.mcp.tool()
        async def circuit_breaker_reset(admin_override: bool = False) -> Dict[str, Any]:
            """Reset the circuit breaker after it has been tripped.

            Args:
                admin_override: Force reset even if trip count >= 3.
            """
            try:
                success = self.circuit_breaker.reset(admin_override=admin_override)
                status = self.circuit_breaker.get_status()
                return {
                    "success": success,
                    "data": {
                        "reset": success,
                        "message": "Circuit breaker reset" if success else "Reset failed - too many trips (admin override required)",
                        "status": status,
                    },
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Circuit breaker reset error: {e}")
                return {"success": False, "error": str(e), "timestamp": datetime.now().isoformat()}

    async def start(self) -> None:
        """Start the MCP server."""
        try:
            # Try to connect to IBKR
            try:
                await self.client.connect()
                logger.success("Connected to IBKR")
            except Exception as e:
                logger.warning(f"IBKR connection failed: {e}")
                logger.info("Server will start - tools will return errors until connected")

            # Start MCP server based on transport
            if self.config.mcp.transport == "stdio":
                await self.mcp.run_async(transport="stdio")
            else:
                await self.mcp.run_async(
                    transport=self.config.mcp.transport,
                    host=self.config.mcp.host,
                    port=self.config.mcp.port,
                )

        except Exception as e:
            logger.error(f"Server start error: {e}")
            raise

    async def stop(self) -> None:
        """Stop the MCP server."""
        logger.info("Stopping IBKR MCP Server...")
        try:
            await self.client.disconnect()
        except Exception as e:
            logger.warning(f"Disconnect error: {e}")
