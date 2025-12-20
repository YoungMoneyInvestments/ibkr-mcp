"""
Configuration models for IBKR MCP Server.
"""

import os
from typing import Optional
from pydantic import BaseModel, Field


class IBKRConfig(BaseModel):
    """IBKR connection configuration."""

    host: str = Field(default="127.0.0.1", description="TWS/Gateway host")
    port: int = Field(default=7497, description="TWS/Gateway port (7497=paper, 7496=live)")
    client_id: int = Field(default=1, description="Client ID for connection")
    timeout: int = Field(default=30, description="Connection timeout in seconds")
    readonly: bool = Field(default=False, description="Read-only mode")

    # Rate limiting
    requests_per_second: float = Field(default=45.0, description="Max requests per second")

    # Data settings
    data_timeout: float = Field(default=2.0, description="Market data timeout")
    market_timezone: str = Field(default="America/New_York", description="Market timezone")

    # Reconnection
    max_reconnect_attempts: int = Field(default=5, description="Max reconnection attempts")
    reconnect_delay: float = Field(default=2.0, description="Delay between reconnection attempts")

    @classmethod
    def from_env(cls) -> "IBKRConfig":
        """Create config from environment variables."""
        return cls(
            host=os.getenv("IBKR_HOST", "127.0.0.1"),
            port=int(os.getenv("IBKR_PORT", "7497")),
            client_id=int(os.getenv("IBKR_CLIENT_ID", "1")),
            timeout=int(os.getenv("IBKR_TIMEOUT", "30")),
            readonly=os.getenv("IBKR_READONLY", "false").lower() == "true",
            requests_per_second=float(os.getenv("IBKR_RATE_LIMIT", "45")),
            data_timeout=float(os.getenv("IBKR_DATA_TIMEOUT", "2.0")),
            market_timezone=os.getenv("IBKR_TIMEZONE", "America/New_York"),
        )


class MCPConfig(BaseModel):
    """MCP server configuration."""

    host: str = Field(default="127.0.0.1", description="MCP server host")
    port: int = Field(default=8080, description="MCP server port")
    transport: str = Field(default="stdio", description="Transport type (stdio, sse, streamable-http)")


class RiskConfig(BaseModel):
    """Risk management configuration."""

    max_loss_per_minute: float = Field(default=1000.0, description="Max loss per minute before circuit breaker")
    max_trades_per_minute: int = Field(default=50, description="Max trades per minute")
    max_daily_loss: float = Field(default=5000.0, description="Max daily loss limit")
    max_position_size: float = Field(default=10000.0, description="Max single position value")
    max_margin_utilization: float = Field(default=50.0, description="Max margin utilization %")
    max_concentration: float = Field(default=20.0, description="Max single position concentration %")


class ServerConfig(BaseModel):
    """Main server configuration."""

    ibkr: IBKRConfig = Field(default_factory=IBKRConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Create config from environment variables."""
        return cls(
            ibkr=IBKRConfig.from_env(),
            mcp=MCPConfig(
                host=os.getenv("MCP_HOST", "127.0.0.1"),
                port=int(os.getenv("MCP_PORT", "8080")),
                transport=os.getenv("MCP_TRANSPORT", "stdio"),
            ),
            risk=RiskConfig(
                max_loss_per_minute=float(os.getenv("RISK_MAX_LOSS_PER_MIN", "1000")),
                max_trades_per_minute=int(os.getenv("RISK_MAX_TRADES_PER_MIN", "50")),
                max_daily_loss=float(os.getenv("RISK_MAX_DAILY_LOSS", "5000")),
                max_position_size=float(os.getenv("RISK_MAX_POSITION", "10000")),
            ),
        )
