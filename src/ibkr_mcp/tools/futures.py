"""
Futures trading tools for IBKR MCP Server.

Provides futures chain retrieval, rollover detection, and contract management.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ib_async import Future, Contract

from ..exceptions import DataError

logger = logging.getLogger(__name__)


async def get_futures_chain(
    client: Any,
    underlying: str,
    exchange: str = "CME"
) -> Dict[str, Any]:
    """
    Get all available futures contracts for an underlying.

    Args:
        client: IBKRClient instance
        underlying: Futures symbol (e.g., 'ES', 'CL', 'GC')
        exchange: Futures exchange (default: CME)

    Returns:
        Dictionary containing:
            - success: Boolean status
            - underlying: Symbol
            - exchange: Exchange
            - contracts: List of futures contracts with details
            - timestamp: Query timestamp
    """
    try:
        # Create a generic future contract
        base_contract = Future(symbol=underlying, exchange=exchange)

        # Get contract details for all expiries
        contracts = client.ib.reqContractDetails(base_contract)

        chain = []
        for cd in contracts:
            contract = cd.contract
            chain.append({
                'symbol': contract.symbol,
                'local_symbol': contract.localSymbol,  # e.g., 'ESZ5' for Dec 2025
                'con_id': contract.conId,
                'last_trade_date': contract.lastTradeDateOrContractMonth,
                'multiplier': float(contract.multiplier) if contract.multiplier else 1,
                'exchange': contract.exchange,
                'trading_class': contract.tradingClass,
                'min_tick': cd.minTick,
                'is_continuous': False
            })

        # Sort by expiration date
        chain.sort(key=lambda x: x['last_trade_date'])

        # Mark front month
        if chain:
            chain[0]['is_front_month'] = True

        return {
            'success': True,
            'underlying': underlying,
            'exchange': exchange,
            'contract_count': len(chain),
            'contracts': chain,
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error getting futures chain for {underlying}: {e}")
        raise DataError(f"Failed to get futures chain: {e}")


async def detect_rollover_needed(
    client: Any,
    symbol: str,
    exchange: str = "CME",
    days_before: int = 5
) -> Dict[str, Any]:
    """
    Detect if contract rollover is needed for futures.

    Args:
        client: IBKRClient instance
        symbol: Futures symbol
        exchange: Futures exchange
        days_before: Days before expiry to trigger rollover recommendation

    Returns:
        Dictionary containing:
            - rollover_needed: Boolean
            - current_contract: Front month contract details
            - next_contract: Next month contract details
            - days_to_expiry: Days until current contract expires
            - recommendation: Rollover recommendation message
            - timestamp: Query timestamp
    """
    try:
        chain_result = await get_futures_chain(client, symbol, exchange)

        if not chain_result['success'] or not chain_result['contracts']:
            return {
                'success': False,
                'rollover_needed': False,
                'error': 'No contracts found',
                'timestamp': datetime.now().isoformat()
            }

        contracts = chain_result['contracts']
        front_month = contracts[0]
        next_month = contracts[1] if len(contracts) > 1 else None

        # Parse expiration date
        expiry_str = str(front_month['last_trade_date'])
        expiry_date = datetime.strptime(expiry_str[:8], '%Y%m%d')
        days_to_expiry = (expiry_date - datetime.now()).days

        rollover_needed = days_to_expiry <= days_before

        return {
            'success': True,
            'rollover_needed': rollover_needed,
            'current_contract': front_month,
            'next_contract': next_month,
            'days_to_expiry': days_to_expiry,
            'recommendation': (
                f"Roll to {next_month['local_symbol']}"
                if rollover_needed and next_month
                else None
            ),
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error detecting rollover for {symbol}: {e}")
        return {
            'success': False,
            'rollover_needed': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


async def get_contract_by_conid(
    client: Any,
    con_id: int
) -> Dict[str, Any]:
    """
    Get contract details by contract ID.

    Args:
        client: IBKRClient instance
        con_id: IBKR contract ID

    Returns:
        Dictionary containing:
            - success: Boolean status
            - contract: Contract details (if found)
            - timestamp: Query timestamp
    """
    try:
        # Check cache first if available
        if hasattr(client, '_conid_map') and con_id in client._conid_map:
            cached_contract = client._conid_map[con_id]
            return {
                'success': True,
                'contract': {
                    'con_id': cached_contract.conId,
                    'symbol': cached_contract.symbol,
                    'sec_type': cached_contract.secType,
                    'exchange': cached_contract.exchange,
                    'currency': cached_contract.currency,
                    'local_symbol': cached_contract.localSymbol
                },
                'cached': True,
                'timestamp': datetime.now().isoformat()
            }

        # Request contract details
        contract = Contract()
        contract.conId = con_id
        details = client.ib.reqContractDetails(contract)

        if details and len(details) > 0:
            resolved = details[0].contract
            if resolved:
                # Cache the contract if caching is available
                if hasattr(client, '_conid_map'):
                    if len(client._conid_map) >= getattr(client, '_max_cache_size', 1000):
                        # Remove oldest entry (first in dict)
                        oldest_key = next(iter(client._conid_map))
                        del client._conid_map[oldest_key]
                    client._conid_map[con_id] = resolved

                return {
                    'success': True,
                    'contract': {
                        'con_id': resolved.conId,
                        'symbol': resolved.symbol,
                        'sec_type': resolved.secType,
                        'exchange': resolved.exchange,
                        'currency': resolved.currency,
                        'local_symbol': resolved.localSymbol
                    },
                    'cached': False,
                    'timestamp': datetime.now().isoformat()
                }

        return {
            'success': False,
            'error': f'No contract found for conId {con_id}',
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error getting contract for conId {con_id}: {e}")
        return {
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


def _get_continuous_contract(symbol: str, exchange: str = "CME") -> Contract:
    """
    Get continuous contract for historical data.

    Args:
        symbol: Futures symbol
        exchange: Futures exchange

    Returns:
        Continuous futures contract
    """
    continuous = Future(
        symbol=symbol,
        exchange=exchange,
        includeExpired=False
    )
    # Set to continuous contract using IB notation
    continuous.localSymbol = symbol + "!"
    return continuous


def _get_front_month_contract(client: Any, symbol: str, exchange: str = "CME") -> Contract:
    """
    Get the front month (most active) contract for trading.

    Args:
        client: IBKRClient instance
        symbol: Futures symbol
        exchange: Futures exchange

    Returns:
        Front month contract
    """
    try:
        # Create generic future
        base = Future(symbol=symbol, exchange=exchange)

        # Get all contracts
        details = client.ib.reqContractDetails(base)

        if not details:
            raise ValueError(f"No contracts found for {symbol} on {exchange}")

        # Sort by lastTradeDateOrContractMonth to get nearest expiry
        details.sort(key=lambda x: x.contract.lastTradeDateOrContractMonth)

        # Return the front month contract
        if details and len(details) > 0:
            return details[0].contract
        else:
            raise ValueError(f"No contracts found for {symbol}")

    except Exception as e:
        logger.error(f"Error getting front month for {symbol}: {e}")
        raise
