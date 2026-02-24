"""Tests for configuration models and utility functions."""

import os
from unittest.mock import patch

import pytest

from ibkr_mcp.config import (
    CONNECTION_PRESETS,
    IBKRConfig,
    MCPConfig,
    RiskConfig,
    ServerConfig,
    get_port_from_mode,
)


class TestGetPortFromMode:
    """Test get_port_from_mode utility function."""

    def test_tws_paper(self):
        assert get_port_from_mode("tws_paper") == 7497

    def test_tws_live(self):
        assert get_port_from_mode("tws_live") == 7496

    def test_gateway_paper(self):
        assert get_port_from_mode("gateway_paper") == 4002

    def test_gateway_live(self):
        assert get_port_from_mode("gateway_live") == 4001

    def test_case_insensitive(self):
        assert get_port_from_mode("TWS_PAPER") == 7497
        assert get_port_from_mode("Tws_Live") == 7496

    def test_invalid_mode_returns_fallback(self):
        assert get_port_from_mode("invalid") == 7497

    def test_none_returns_fallback(self):
        assert get_port_from_mode(None) == 7497

    def test_empty_string_returns_fallback(self):
        assert get_port_from_mode("") == 7497

    def test_custom_fallback(self):
        assert get_port_from_mode("invalid", fallback_port=9999) == 9999

    def test_none_with_custom_fallback(self):
        assert get_port_from_mode(None, fallback_port=4444) == 4444


class TestConnectionPresets:
    """Test CONNECTION_PRESETS dictionary."""

    def test_all_presets_have_port(self):
        for name, preset in CONNECTION_PRESETS.items():
            assert "port" in preset, f"Preset '{name}' missing 'port'"

    def test_all_presets_have_description(self):
        for name, preset in CONNECTION_PRESETS.items():
            assert "description" in preset, f"Preset '{name}' missing 'description'"

    def test_expected_presets_exist(self):
        expected = {"tws_paper", "tws_live", "gateway_paper", "gateway_live"}
        assert set(CONNECTION_PRESETS.keys()) == expected


class TestIBKRConfig:
    """Test IBKRConfig model."""

    def test_defaults(self):
        config = IBKRConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 7497
        assert config.client_id == 1
        assert config.timeout == 30
        assert config.readonly is False
        assert config.mode is None
        assert config.client_id_auto_retry is True
        assert config.client_id_max_attempts == 5
        assert config.requests_per_second == 45.0
        assert config.data_timeout == 2.0
        assert config.market_timezone == "America/New_York"
        assert config.max_reconnect_attempts == 5
        assert config.reconnect_delay == 2.0

    def test_custom_values(self):
        config = IBKRConfig(
            host="192.168.1.1",
            port=7496,
            client_id=5,
            timeout=60,
            readonly=True,
        )
        assert config.host == "192.168.1.1"
        assert config.port == 7496
        assert config.client_id == 5
        assert config.timeout == 60
        assert config.readonly is True

    def test_from_env_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = IBKRConfig.from_env()
        assert config.host == "127.0.0.1"
        assert config.port == 7497
        assert config.client_id == 1
        assert config.timeout == 30
        assert config.readonly is False

    def test_from_env_with_values(self):
        env = {
            "IBKR_HOST": "10.0.0.1",
            "IBKR_PORT": "7496",
            "IBKR_CLIENT_ID": "42",
            "IBKR_TIMEOUT": "60",
            "IBKR_READONLY": "true",
            "IBKR_CLIENT_ID_AUTO_RETRY": "false",
            "IBKR_CLIENT_ID_MAX_ATTEMPTS": "3",
            "IBKR_RATE_LIMIT": "30",
            "IBKR_DATA_TIMEOUT": "5.0",
            "IBKR_TIMEZONE": "US/Central",
        }
        with patch.dict(os.environ, env, clear=True):
            config = IBKRConfig.from_env()
        assert config.host == "10.0.0.1"
        assert config.port == 7496
        assert config.client_id == 42
        assert config.timeout == 60
        assert config.readonly is True
        assert config.client_id_auto_retry is False
        assert config.client_id_max_attempts == 3
        assert config.requests_per_second == 30.0
        assert config.data_timeout == 5.0
        assert config.market_timezone == "US/Central"

    def test_from_env_with_mode(self):
        env = {"IBKR_MODE": "gateway_live"}
        with patch.dict(os.environ, env, clear=True):
            config = IBKRConfig.from_env()
        assert config.mode == "gateway_live"
        assert config.port == 4001

    def test_from_env_mode_overrides_port(self):
        env = {"IBKR_MODE": "tws_live", "IBKR_PORT": "9999"}
        with patch.dict(os.environ, env, clear=True):
            config = IBKRConfig.from_env()
        # Mode should take precedence over explicit port
        assert config.port == 7496

    def test_get_mode_description_with_mode(self):
        config = IBKRConfig(mode="tws_paper")
        assert config.get_mode_description() == "TWS Paper Trading"

    def test_get_mode_description_inferred_from_port(self):
        config = IBKRConfig(port=4002)
        assert config.get_mode_description() == "IB Gateway Paper Trading"

    def test_get_mode_description_custom_port(self):
        config = IBKRConfig(port=9999)
        assert config.get_mode_description() == "Custom (port 9999)"


class TestMCPConfig:
    """Test MCPConfig model."""

    def test_defaults(self):
        config = MCPConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 8080
        assert config.transport == "stdio"

    def test_custom_values(self):
        config = MCPConfig(host="0.0.0.0", port=3000, transport="sse")
        assert config.host == "0.0.0.0"
        assert config.port == 3000
        assert config.transport == "sse"


class TestRiskConfig:
    """Test RiskConfig model."""

    def test_defaults(self):
        config = RiskConfig()
        assert config.max_loss_per_minute == 1000.0
        assert config.max_trades_per_minute == 50
        assert config.max_daily_loss == 5000.0
        assert config.max_position_size == 10000.0
        assert config.max_margin_utilization == 50.0
        assert config.max_concentration == 20.0

    def test_custom_values(self):
        config = RiskConfig(
            max_loss_per_minute=500,
            max_trades_per_minute=10,
            max_daily_loss=2000,
            max_position_size=5000,
            max_margin_utilization=80,
            max_concentration=30,
        )
        assert config.max_loss_per_minute == 500
        assert config.max_trades_per_minute == 10
        assert config.max_daily_loss == 2000
        assert config.max_position_size == 5000
        assert config.max_margin_utilization == 80
        assert config.max_concentration == 30


class TestServerConfig:
    """Test ServerConfig model."""

    def test_defaults(self):
        config = ServerConfig()
        assert isinstance(config.ibkr, IBKRConfig)
        assert isinstance(config.mcp, MCPConfig)
        assert isinstance(config.risk, RiskConfig)

    def test_nested_defaults(self):
        config = ServerConfig()
        assert config.ibkr.port == 7497
        assert config.mcp.transport == "stdio"
        assert config.risk.max_daily_loss == 5000.0

    def test_custom_nested(self):
        config = ServerConfig(
            ibkr=IBKRConfig(port=7496),
            mcp=MCPConfig(transport="sse"),
            risk=RiskConfig(max_daily_loss=10000),
        )
        assert config.ibkr.port == 7496
        assert config.mcp.transport == "sse"
        assert config.risk.max_daily_loss == 10000

    def test_from_env_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = ServerConfig.from_env()
        assert config.ibkr.port == 7497
        assert config.mcp.transport == "stdio"
        assert config.risk.max_daily_loss == 5000

    def test_from_env_with_values(self):
        env = {
            "IBKR_HOST": "10.0.0.1",
            "IBKR_PORT": "7496",
            "MCP_HOST": "0.0.0.0",
            "MCP_PORT": "3000",
            "MCP_TRANSPORT": "sse",
            "RISK_MAX_LOSS_PER_MIN": "500",
            "RISK_MAX_TRADES_PER_MIN": "20",
            "RISK_MAX_DAILY_LOSS": "2000",
            "RISK_MAX_POSITION": "5000",
        }
        with patch.dict(os.environ, env, clear=True):
            config = ServerConfig.from_env()
        assert config.ibkr.host == "10.0.0.1"
        assert config.ibkr.port == 7496
        assert config.mcp.host == "0.0.0.0"
        assert config.mcp.port == 3000
        assert config.mcp.transport == "sse"
        assert config.risk.max_loss_per_minute == 500
        assert config.risk.max_trades_per_minute == 20
        assert config.risk.max_daily_loss == 2000
        assert config.risk.max_position_size == 5000

    def test_conftest_ibkr_config_fixture(self, ibkr_config):
        """Verify the conftest fixture works correctly."""
        assert ibkr_config.client_id == 99
        assert ibkr_config.readonly is True
        assert ibkr_config.timeout == 10

    def test_conftest_server_config_fixture(self, server_config):
        """Verify the conftest server_config fixture works correctly."""
        assert server_config.ibkr.client_id == 99
        assert server_config.mcp.transport == "stdio"
