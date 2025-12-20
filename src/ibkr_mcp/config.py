"""
Configuration models for IBKR MCP Server.
"""

import os
from typing import Optional, Dict
from pydantic import BaseModel, Field


# Connection presets for different IBKR platforms
CONNECTION_PRESETS: Dict[str, Dict[str, any]] = {
    "tws_paper": {"port": 7497, "description": "TWS Paper Trading"},
    "tws_live": {"port": 7496, "description": "TWS Live Trading"},
    "gateway_paper": {"port": 4002, "description": "IB Gateway Paper Trading"},
    "gateway_live": {"port": 4001, "description": "IB Gateway Live Trading"},
}


def get_port_from_mode(mode: Optional[str], fallback_port: int = 7497) -> int:
    """
    Get port number from connection mode preset.

    Args:
        mode: Connection mode (tws_paper, tws_live, gateway_paper, gateway_live)
        fallback_port: Port to use if mode is not specified or invalid

    Returns:
        Port number for the specified mode
    """
    if mode and mode.lower() in CONNECTION_PRESETS:
        return CONNECTION_PRESETS[mode.lower()]["port"]
    return fallback_port


class IBKRConfig(BaseModel):
    """IBKR connection configuration."""

    host: str = Field(default="127.0.0.1", description="TWS/Gateway host")
    port: int = Field(default=7497, description="TWS/Gateway port (7497=paper, 7496=live)")
    client_id: int = Field(default=1, description="Starting client ID for connection")
    timeout: int = Field(default=30, description="Connection timeout in seconds")
    readonly: bool = Field(default=False, description="Read-only mode")

    # Connection mode preset
    mode: Optional[str] = Field(
        default=None,
        description="Connection preset: tws_paper, tws_live, gateway_paper, gateway_live"
    )

    # Client ID retry settings
    client_id_auto_retry: bool = Field(
        default=True,
        description="Auto-retry with different client ID on connection failure"
    )
    client_id_max_attempts: int = Field(
        default=5,
        description="Max attempts to find available client ID"
    )

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
        # Check for mode preset first
        mode = os.getenv("IBKR_MODE")

        # If mode is set, use preset port; otherwise use IBKR_PORT or default
        if mode:
            port = get_port_from_mode(mode)
        else:
            port = int(os.getenv("IBKR_PORT", "7497"))

        return cls(
            host=os.getenv("IBKR_HOST", "127.0.0.1"),
            port=port,
            client_id=int(os.getenv("IBKR_CLIENT_ID", "1")),
            timeout=int(os.getenv("IBKR_TIMEOUT", "30")),
            readonly=os.getenv("IBKR_READONLY", "false").lower() == "true",
            mode=mode,
            client_id_auto_retry=os.getenv("IBKR_CLIENT_ID_AUTO_RETRY", "true").lower() == "true",
            client_id_max_attempts=int(os.getenv("IBKR_CLIENT_ID_MAX_ATTEMPTS", "5")),
            requests_per_second=float(os.getenv("IBKR_RATE_LIMIT", "45")),
            data_timeout=float(os.getenv("IBKR_DATA_TIMEOUT", "2.0")),
            market_timezone=os.getenv("IBKR_TIMEZONE", "America/New_York"),
        )

    def get_mode_description(self) -> str:
        """Get human-readable description of current connection mode."""
        if self.mode and self.mode.lower() in CONNECTION_PRESETS:
            return CONNECTION_PRESETS[self.mode.lower()]["description"]

        # Infer from port if mode not explicitly set
        for preset_name, preset_info in CONNECTION_PRESETS.items():
            if preset_info["port"] == self.port:
                return preset_info["description"]

        return f"Custom (port {self.port})"


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
