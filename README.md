# IBKR MCP Server

**A self-hosted, institutional-grade risk engine for Interactive Brokers — with a full trading, market-data, and execution stack wired behind it.**

You run this against your own IB Gateway, on your own account, under your own control. Every order it can place — market, limit, bracket, OCA, trailing stop, TWAP/VWAP/DarkIce/Adaptive algos — fires *through* a real risk layer first: parametric and historical Value-at-Risk, Kelly and volatility-based position sizing, margin/concentration/buying-power limits, and an automatic loss circuit-breaker that halts trading when you cross a drawdown threshold. Exposing IBKR to an AI assistant is the table stakes. The risk stack is the product.

## Why this vs IBKR's official MCP / the free clones

IBKR now ships a free official MCP server, and there are 10+ open-source IBKR MCP clones. They connect an LLM to your account and let it read data and route orders. That's it. **None of them ship the risk layer** — no VaR, no Kelly/vol sizing engine, no enforced margin/concentration limits, no automatic loss circuit-breaker. The most complete OSS clone stops at option Greeks and a concentration check.

| | Official IBKR MCP / OSS clones | This server |
|---|---|---|
| Connect an LLM to IBKR | ✅ | ✅ |
| Market data, orders, options, futures, scanners | ✅ | ✅ |
| Bracket / OCA / trailing / TWAP / VWAP / DarkIce algos | partial | ✅ |
| Parametric + historical VaR | ❌ | ✅ |
| Kelly / volatility position sizing | ❌ | ✅ |
| Enforced margin / concentration / buying-power limits | ❌ | ✅ |
| Automatic loss circuit-breaker (halts trading) | ❌ | ✅ |
| Self-hosted on your own Gateway + account | — | ✅ |

If all you need is "an LLM that can see my IBKR account," use the free official one. This exists for quant prosumers and small funds who want the AI to trade *inside* hard risk rails they define.

## Safety model — you own the risk

This is a tool you **self-host and run against your own account and your own IB Gateway**. There is no hosted service in the middle touching accounts you don't own, and there is no third party taking custody of anything.

- **Default posture is approval-required.** Out of the box, the assistant proposes orders; a human confirms before anything routes.
- **Fully-autonomous (no-human-click) execution is an explicit opt-in** that *you* enable, on *your* account, on *your* Gateway. It is off until you turn it on.
- **The risk gates are always in the path** regardless of mode — approval-required or autonomous, orders still pass through VaR, sizing, limit, and circuit-breaker checks before reaching the broker.

This is deliberately different from IBKR's liability-driven mandatory-approval design: you decide how much autonomy to grant, because you're the one holding the account and the risk.

## Features

### Risk Management
- **Value at Risk** - Parametric and historical VaR
- **Position Sizing** - Fixed risk, Kelly criterion, volatility-based
- **Risk Limits** - Margin utilization, concentration, buying power checks
- **Circuit Breaker** - Automatic trading halt on excessive losses

### Trading
- **Basic Orders** - Market, limit, stop orders
- **Bracket Orders** - Entry + take profit + stop loss
- **Trailing Stops** - By amount or percentage
- **OCA Orders** - One-Cancels-All order groups
- **Algo Orders** - TWAP, VWAP, Arrival Price, DarkIce, Adaptive, and more

### Account & Portfolio
- **Account Summary** - Balances, buying power, margin status
- **Positions** - Current holdings with P&L
- **Portfolio Analysis** - Allocation by asset class, symbol, currency
- **Rebalancing** - Calculate and execute rebalancing trades

### Market Data
- **Real-time Prices** - Live quotes with fast failover
- **Historical Data** - OHLCV bars with pagination
- **Level 2** - Order book / market depth
- **Streaming** - Real-time data for HFT strategies
- **Symbol Search** - Find tradable instruments

### Options
- **Option Chains** - Full chain with Greeks
- **Spread Analysis** - Bull call, bear put, straddle, strangle, iron condor

### Futures
- **Futures Chain** - All available contracts
- **Rollover Detection** - Automatic expiry alerts
- **Continuous Contracts** - For historical analysis

### Market Scanners
- **Pre-built Scans** - Top gainers, losers, most active, unusual volume
- **Custom Scanners** - Build your own with filters
- **Options Volume** - Unusual options activity

## Installation

```bash
# From source (this is a private, proprietary repo — not published to PyPI)
git clone git@github.com:YoungMoneyInvestments/ibkr-mcp.git
cd ibkr-mcp
pip install -e .
```

> Note: an unrelated `ibkr-mcp` package exists on public PyPI — it is NOT this project. Install from source only.

## Prerequisites

1. **Interactive Brokers Account** - Live or paper trading account
2. **TWS or IB Gateway** - Running and accepting API connections
3. **API Configuration** in TWS/Gateway:
   - Enable API: Configure > API > Settings > Enable ActiveX and Socket Clients
   - Trusted IPs: Add 127.0.0.1
   - Port: 7497 (paper) or 7496 (live)

## Quick Start

### 1. Start TWS/IB Gateway

Open TWS or IB Gateway and log in. Ensure API connections are enabled.

### 2. Configure Claude Desktop

Add to your Claude Desktop `mcp.json`:

```json
{
  "mcpServers": {
    "ibkr": {
      "command": "ibkr-mcp",
      "args": ["--port", "7497"]
    }
  }
}
```

For live trading (use with caution):
```json
{
  "mcpServers": {
    "ibkr": {
      "command": "ibkr-mcp",
      "args": ["--port", "7496"]
    }
  }
}
```

### 3. Use with Claude

```
"Show me my current positions"
"Get a quote for AAPL"
"Place a limit order to buy 100 shares of MSFT at $400"
"What's the option chain for SPY?"
"Scan for top percentage gainers today"
"Calculate position size for TSLA with $500 risk and stop at $350"
```

## CLI Usage

```bash
# Default settings (paper trading, stdio transport)
ibkr-mcp

# Connect to live trading
ibkr-mcp --port 7496

# Read-only mode (no trading)
ibkr-mcp --readonly

# SSE transport for web clients
ibkr-mcp --transport sse --mcp-port 8080

# Verbose logging
ibkr-mcp -v

# Full options
ibkr-mcp --help
```

## Environment Variables

### Connection Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `IBKR_MODE` | - | Connection preset (see below) |
| `IBKR_HOST` | 127.0.0.1 | TWS/Gateway host |
| `IBKR_PORT` | 7497 | TWS/Gateway port (overridden by IBKR_MODE) |
| `IBKR_CLIENT_ID` | 1 | Starting client ID |
| `IBKR_CLIENT_ID_AUTO_RETRY` | true | Auto-retry with different client ID on conflict |
| `IBKR_CLIENT_ID_MAX_ATTEMPTS` | 5 | Max attempts to find available client ID |
| `IBKR_READONLY` | false | Disable trading |
| `IBKR_TIMEOUT` | 30 | Connection timeout (seconds) |
| `MCP_TRANSPORT` | stdio | Transport type |

### Connection Mode Presets

Use `IBKR_MODE` to easily switch between platforms:

| Mode | Port | Description |
|------|------|-------------|
| `tws_paper` | 7497 | TWS Paper Trading (default) |
| `tws_live` | 7496 | TWS Live Trading |
| `gateway_paper` | 4002 | IB Gateway Paper Trading |
| `gateway_live` | 4001 | IB Gateway Live Trading |

**Examples:**
```bash
# Connect to IB Gateway paper trading
IBKR_MODE=gateway_paper ibkr-mcp

# Connect to TWS live with custom client ID
IBKR_MODE=tws_live IBKR_CLIENT_ID=10 ibkr-mcp

# Disable client ID auto-retry
IBKR_CLIENT_ID_AUTO_RETRY=false ibkr-mcp
```

## Available Tools

### Connection
- `connection_status` - Check IBKR connection
- `reconnect` - Reconnect to IBKR

### Account
- `get_account_summary` - Account balances and values
- `get_positions` - Current holdings
- `analyze_portfolio_allocation` - Portfolio breakdown
- `calculate_rebalancing_orders` - Rebalancing plan
- `execute_rebalancing` - Execute rebalancing trades

### Trading
- `place_order` - Market/limit/stop orders
- `place_bracket_order` - Bracket orders
- `place_trailing_stop` - Trailing stop orders
- `place_one_cancels_all` - OCA order groups
- `place_algo_order` - Algorithmic orders
- `cancel_order` - Cancel an order
- `get_open_orders` - List open orders

### Market Data
- `get_realtime_price` - Real-time quote
- `get_historical_data` - Historical bars
- `get_order_book` - Level 2 data
- `search_symbols` - Symbol search
- `get_news` - News bulletins

### Options
- `get_option_chain` - Options with Greeks
- `analyze_option_spread` - Spread strategy analysis

### Futures
- `get_futures_chain` - Available contracts
- `detect_rollover_needed` - Expiry alerts

### Scanners
- `scan_market` - Pre-built market scans
- `create_custom_scanner` - Custom scans
- `scan_options_volume` - Unusual options activity

### Risk
- `calculate_position_size` - Position sizing
- `check_risk_limits` - Risk status
- `set_stop_loss_orders` - Auto stop losses
- `calculate_var` - Value at Risk

## Docker

```bash
docker build -t ibkr-mcp .
docker run -e IBKR_HOST=host.docker.internal ibkr-mcp
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src

# Linting
ruff check src
```

## Safety Features

- **Read-only Mode** - Disable all trading operations
- **Rate Limiting** - Stay under IBKR API limits
- **Circuit Breaker** - Automatic halt on excessive losses
- **Input Validation** - Validate all order parameters
- **Error Recovery** - Automatic reconnection with backoff

## License

Proprietary — Copyright (c) 2026 Cameron Bennion. All Rights Reserved. See [LICENSE](LICENSE).

## Disclaimer

This software is for educational and informational purposes only. Trading involves substantial risk of loss. Past performance is not indicative of future results. Always test with paper trading first.
