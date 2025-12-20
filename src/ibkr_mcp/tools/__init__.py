"""
IBKR MCP Tools - Modular tool functions for MCP server registration.

This package contains all the tool implementations that can be registered
with the MCP server. Each module exports functions that follow the pattern:
- Accept an IB client instance as the first parameter
- Return Dict[str, Any] with 'success', 'data', 'timestamp' keys
- Include proper error handling
- Use type hints
"""

from .account import (
    get_account_summary,
    get_positions,
    analyze_portfolio_allocation,
    calculate_rebalancing_orders,
    execute_rebalancing,
)

from .market_data import (
    get_realtime_price,
    get_historical_data,
    stream_market_data,
    get_order_book,
    calculate_slippage,
    get_news,
    search_symbols,
)

from .orders import (
    place_order,
    cancel_order,
    get_open_orders,
)

from .orders_advanced import (
    place_bracket_order,
    place_trailing_stop,
    place_one_cancels_all,
    place_algo_order,
    create_twap_params,
    create_vwap_params,
    create_arrival_price_params,
    create_dark_ice_params,
    create_adaptive_params,
    create_accumulate_distribute_params,
    create_balance_impact_risk_params,
    create_min_impact_params,
)

from .options import (
    get_option_chain,
    analyze_option_spread,
)

from .futures import (
    get_futures_chain,
    detect_rollover_needed,
    get_contract_by_conid,
)

from .scanners import (
    scan_market,
    create_custom_scanner,
    scan_options_volume,
)

from .risk import (
    calculate_position_size,
    check_risk_limits,
    set_stop_loss_orders,
    calculate_var,
)

__all__ = [
    # Account & Portfolio Management
    "get_account_summary",
    "get_positions",
    "analyze_portfolio_allocation",
    "calculate_rebalancing_orders",
    "execute_rebalancing",
    # Market Data
    "get_realtime_price",
    "get_historical_data",
    "stream_market_data",
    "get_order_book",
    "calculate_slippage",
    "get_news",
    "search_symbols",
    # Basic Order Management
    "place_order",
    "cancel_order",
    "get_open_orders",
    # Advanced Order Management
    "place_bracket_order",
    "place_trailing_stop",
    "place_one_cancels_all",
    "place_algo_order",
    # Algo Parameter Helpers
    "create_twap_params",
    "create_vwap_params",
    "create_arrival_price_params",
    "create_dark_ice_params",
    "create_adaptive_params",
    "create_accumulate_distribute_params",
    "create_balance_impact_risk_params",
    "create_min_impact_params",
    # Options Trading
    "get_option_chain",
    "analyze_option_spread",
    # Futures Trading
    "get_futures_chain",
    "detect_rollover_needed",
    "get_contract_by_conid",
    # Market Scanners
    "scan_market",
    "create_custom_scanner",
    "scan_options_volume",
    # Risk Management
    "calculate_position_size",
    "check_risk_limits",
    "set_stop_loss_orders",
    "calculate_var",
]
