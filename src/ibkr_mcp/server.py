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


class IBKRMCPServer:
    """IBKR MCP Server - Full-featured Interactive Brokers integration."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.client = IBKRClient(config.ibkr)
        self.mcp = FastMCP(
            "IBKR MCP Server",
            version="1.0.0",
            description="Full-featured Interactive Brokers integration for AI assistants",
        )
        self._setup_tools()

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
