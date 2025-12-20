# IBKR MCP Server

Full-featured Interactive Brokers MCP (Model Context Protocol) server for AI assistants like Claude.

## Features

### Account & Portfolio
- **Account Summary** - Balances, buying power, margin status
- **Positions** - Current holdings with P&L
- **Portfolio Analysis** - Allocation by asset class, symbol, currency
- **Rebalancing** - Calculate and execute rebalancing trades

### Trading
- **Basic Orders** - Market, limit, stop orders
- **Bracket Orders** - Entry + take profit + stop loss
- **Trailing Stops** - By amount or percentage
- **OCA Orders** - One-Cancels-All order groups
- **Algo Orders** - TWAP, VWAP, Arrival Price, DarkIce, Adaptive, and more

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

### Risk Management
- **Position Sizing** - Fixed risk, Kelly criterion, volatility-based
- **Risk Limits** - Margin utilization, concentration, buying power checks
- **Value at Risk** - Parametric and historical VaR
- **Circuit Breaker** - Automatic trading halt on excessive losses

## Installation

```bash
# From PyPI (recommended)
pip install ibkr-mcp

# From source
git clone https://github.com/cameronbennion/ibkr-mcp.git
cd ibkr-mcp
pip install -e .
```

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

| Variable | Default | Description |
|----------|---------|-------------|
| `IBKR_HOST` | 127.0.0.1 | TWS/Gateway host |
| `IBKR_PORT` | 7497 | TWS/Gateway port |
| `IBKR_CLIENT_ID` | 1 | Connection client ID |
| `IBKR_READONLY` | false | Disable trading |
| `IBKR_TIMEOUT` | 30 | Connection timeout (seconds) |
| `MCP_TRANSPORT` | stdio | Transport type |

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

MIT License - see [LICENSE](LICENSE)

## Disclaimer

This software is for educational and informational purposes only. Trading involves substantial risk of loss. Past performance is not indicative of future results. Always test with paper trading first.
