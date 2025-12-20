"""
Contract creation and management utilities.
"""

from typing import Any, Dict, Optional

from ib_async import Contract, Stock, Option, Future, Forex
from loguru import logger

from ..models import SecType


def create_contract(
    symbol: str,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    expiry: Optional[str] = None,
    strike: Optional[float] = None,
    right: Optional[str] = None,
    local_symbol: Optional[str] = None,
) -> Contract:
    """
    Create an IBKR contract.

    Args:
        symbol: Contract symbol
        sec_type: Security type (STK, OPT, FUT, CASH)
        exchange: Exchange (default: SMART)
        currency: Currency (default: USD)
        expiry: Expiry date for options/futures
        strike: Strike price for options
        right: Option right (C/P)
        local_symbol: Local symbol for futures

    Returns:
        IB Contract object
    """
    sec_type = sec_type.upper()

    if sec_type == "STK":
        contract = Stock(symbol, exchange, currency)

    elif sec_type == "OPT":
        if not all([expiry, strike, right]):
            raise ValueError("Options require expiry, strike, and right")
        contract = Option(symbol, expiry, strike, right, exchange, currency)

    elif sec_type == "FUT":
        contract = Future(symbol, exchange=exchange)
        if local_symbol:
            contract.localSymbol = local_symbol
        if expiry:
            contract.lastTradeDateOrContractMonth = expiry

    elif sec_type == "CASH":
        contract = Forex(symbol)

    else:
        # Generic contract
        contract = Contract()
        contract.symbol = symbol
        contract.secType = sec_type
        contract.exchange = exchange
        contract.currency = currency

    return contract


async def qualify_contract(ib, contract: Contract) -> Optional[Contract]:
    """
    Qualify a contract with IBKR.

    Args:
        ib: IB connection instance
        contract: Contract to qualify

    Returns:
        Qualified contract or None
    """
    try:
        qualified = ib.qualifyContracts(contract)
        if qualified:
            return qualified[0] if isinstance(qualified, list) else qualified
        return None
    except Exception as e:
        logger.error(f"Failed to qualify contract {contract.symbol}: {e}")
        return None


def smart_contract_lookup(
    symbol: str,
    sec_type: str,
    exchange: str,
    use_continuous: bool = False,
    specific_expiry: Optional[str] = None,
) -> Contract:
    """
    Smart contract resolution with fallback strategies.

    For futures:
    - use_continuous=True: Use continuous contract for historical data
    - specific_expiry: Use specific contract like 'ESZ5'
    - Otherwise: Get front month contract

    Args:
        symbol: Contract symbol
        sec_type: Security type
        exchange: Exchange
        use_continuous: Use continuous contract (futures)
        specific_expiry: Specific expiry/local symbol

    Returns:
        Contract object
    """
    sec_type = sec_type.upper()

    if sec_type == "FUT":
        contract = Future(symbol=symbol, exchange=exchange)

        if use_continuous:
            # Continuous contract notation
            contract.localSymbol = f"{symbol}!"
        elif specific_expiry:
            contract.localSymbol = specific_expiry
        # Else: will need to be qualified to get front month

        return contract

    # Non-futures use standard contract creation
    return create_contract(symbol, sec_type, exchange)


def get_front_month_contract(
    ib,
    symbol: str,
    exchange: str = "CME",
) -> Optional[Contract]:
    """
    Get the front month (most active) futures contract.

    Args:
        ib: IB connection instance
        symbol: Futures symbol
        exchange: Exchange

    Returns:
        Front month contract or None
    """
    try:
        base = Future(symbol=symbol, exchange=exchange)
        details = ib.reqContractDetails(base)

        if not details:
            logger.warning(f"No contracts found for {symbol} on {exchange}")
            return None

        # Sort by expiry and get nearest
        details.sort(key=lambda x: x.contract.lastTradeDateOrContractMonth)
        return details[0].contract

    except Exception as e:
        logger.error(f"Error getting front month for {symbol}: {e}")
        return None


def contract_to_dict(contract: Contract) -> Dict[str, Any]:
    """
    Convert contract to dictionary.

    Args:
        contract: IB Contract

    Returns:
        Dict representation
    """
    return {
        "symbol": contract.symbol,
        "sec_type": contract.secType,
        "exchange": contract.exchange,
        "currency": contract.currency,
        "local_symbol": contract.localSymbol,
        "con_id": contract.conId,
        "primary_exchange": getattr(contract, "primaryExchange", None),
    }
