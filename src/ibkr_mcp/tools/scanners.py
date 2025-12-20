"""
Market scanner tools for IBKR MCP Server.

Provides market scanning capabilities including pre-built scanners,
custom scanners, and options volume scanning.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ib_async import ScannerSubscription, TagValue

from ..exceptions import DataError

logger = logging.getLogger(__name__)


async def scan_market(
    client: Any,
    scan_code: str,
    location: str = "STK.US.MAJOR",
    instrument: str = "STK",
    num_rows: int = 50
) -> Dict[str, Any]:
    """
    Use IBKR market scanners to find trading opportunities.

    Common scan codes:
        - TOP_PERC_GAIN: Top percentage gainers
        - TOP_PERC_LOSE: Top percentage losers
        - MOST_ACTIVE: Most active by volume
        - HOT_BY_VOLUME: Unusual volume
        - HIGH_DIV_YIELD: High dividend yield
        - LOW_PE_RATIO: Low P/E ratio
        - HIGH_PE_RATIO: High P/E ratio
        - TOP_TRADE_RATE: Highest trade rate
        - HIGH_VS_13W_HL: Near 13-week high
        - LOW_VS_13W_HL: Near 13-week low

    Args:
        client: IBKRClient instance
        scan_code: Scanner code (see list above)
        location: Location code (default: STK.US.MAJOR)
        instrument: Instrument type (default: STK)
        num_rows: Maximum number of results (default: 50)

    Returns:
        Dictionary containing:
            - success: Boolean status
            - scan_code: Scanner code used
            - location: Location code
            - instrument: Instrument type
            - result_count: Number of results
            - results: List of scan results with market data
            - timestamp: Query timestamp
    """
    try:
        # Create scanner subscription
        scanner = ScannerSubscription(
            instrument=instrument,
            locationCode=location,
            scanCode=scan_code
        )

        # Request scanner data
        scan_data = await client.ib.reqScannerDataAsync(scanner)

        # Limit results
        scan_data = scan_data[:num_rows]

        results = []
        for item in scan_data:
            contract = item.contractDetails.contract

            # Get current market data for each result
            ticker = client.ib.reqMktData(contract)
            await asyncio.sleep(0.2)

            result = {
                "rank": item.rank,
                "symbol": contract.symbol,
                "sec_type": contract.secType,
                "exchange": contract.primaryExchange or contract.exchange,
                "currency": contract.currency,
                "distance": item.distance,
                "benchmark": item.benchmark,
                "projection": item.projection,
                "legs": item.legsStr
            }

            # Add market data if available
            if ticker.marketPrice() and ticker.marketPrice() > 0:
                result["current_price"] = ticker.marketPrice()
                result["volume"] = ticker.volume
                result["bid"] = ticker.bid
                result["ask"] = ticker.ask
                result["high"] = ticker.high
                result["low"] = ticker.low

            client.ib.cancelMktData(contract)
            results.append(result)

        return {
            "success": True,
            "scan_code": scan_code,
            "location": location,
            "instrument": instrument,
            "result_count": len(results),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Market scan failed: {e}")
        raise DataError(f"Market scan failed: {e}")


async def create_custom_scanner(
    client: Any,
    criteria: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Create a custom scanner with specific criteria.

    Criteria can include:
        - min_price: Minimum stock price
        - max_price: Maximum stock price
        - min_volume: Minimum average volume
        - min_market_cap: Minimum market capitalization
        - above_price_sma: Price above SMA (e.g., 50, 200)
        - below_price_sma: Price below SMA
        - volume_rate_change: Volume rate of change threshold
        - price_change_pct: Price change percentage
        - instrument: Instrument type (default: STK)
        - location: Location code (default: STK.US.MAJOR)
        - scan_code: Base scan code (default: TOP_PERC_GAIN)
        - num_rows: Max results (default: 50)

    Args:
        client: IBKRClient instance
        criteria: Dictionary of filter criteria

    Returns:
        Dictionary containing:
            - success: Boolean status
            - criteria: Applied criteria
            - filter_count: Number of filters applied
            - result_count: Number of results
            - results: List of scan results
            - timestamp: Query timestamp
    """
    try:
        # Build scanner subscription
        scanner = ScannerSubscription()
        scanner.instrument = criteria.get("instrument", "STK")
        scanner.locationCode = criteria.get("location", "STK.US.MAJOR")
        scanner.scanCode = criteria.get("scan_code", "TOP_PERC_GAIN")

        # Add filter criteria
        filter_options = []

        if "min_price" in criteria:
            filter_options.append(TagValue("priceAbove", str(criteria["min_price"])))

        if "max_price" in criteria:
            filter_options.append(TagValue("priceBelow", str(criteria["max_price"])))

        if "min_volume" in criteria:
            filter_options.append(TagValue("volumeAbove", str(criteria["min_volume"])))

        if "min_market_cap" in criteria:
            filter_options.append(TagValue("marketCapAbove", str(criteria["min_market_cap"])))

        if "above_price_sma" in criteria:
            filter_options.append(TagValue("priceAboveSMA", str(criteria["above_price_sma"])))

        if "below_price_sma" in criteria:
            filter_options.append(TagValue("priceBelowSMA", str(criteria["below_price_sma"])))

        if "volume_rate_change" in criteria:
            filter_options.append(TagValue("volumeRateAbove", str(criteria["volume_rate_change"])))

        if "price_change_pct" in criteria:
            filter_options.append(TagValue("changePercAbove", str(criteria["price_change_pct"])))

        scanner.scannerSettingPairs = filter_options
        scanner.numberOfRows = criteria.get("num_rows", 50)

        # Request scanner data
        scan_data = await client.ib.reqScannerDataAsync(scanner)

        results = []
        for item in scan_data:
            contract = item.contractDetails.contract
            results.append({
                "rank": item.rank,
                "symbol": contract.symbol,
                "exchange": contract.primaryExchange or contract.exchange,
                "currency": contract.currency,
                "distance": item.distance
            })

        return {
            "success": True,
            "criteria": criteria,
            "filter_count": len(filter_options),
            "result_count": len(results),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Custom scanner failed: {e}")
        raise DataError(f"Custom scanner failed: {e}")


async def scan_options_volume(
    client: Any,
    underlying: Optional[str] = None,
    min_volume: int = 1000,
    min_open_interest: int = 100
) -> Dict[str, Any]:
    """
    Scan for unusual options activity.

    Args:
        client: IBKRClient instance
        underlying: Specific underlying symbol (None for all)
        min_volume: Minimum volume threshold
        min_open_interest: Minimum open interest

    Returns:
        Dictionary containing:
            - success: Boolean status
            - scan_type: Type of scan
            - filters: Applied filters
            - result_count: Number of results
            - results: List of options with unusual activity
            - timestamp: Query timestamp
    """
    try:
        # Create options scanner
        scanner = ScannerSubscription()
        scanner.instrument = "OPT"
        scanner.locationCode = "OPT.US"
        scanner.scanCode = "HIGH_OPT_VOLUME_PUT_CALL_RATIO"

        filter_options = []

        if underlying:
            filter_options.append(TagValue("underConID", underlying))

        if min_volume:
            filter_options.append(TagValue("volumeAbove", str(min_volume)))

        if min_open_interest:
            filter_options.append(TagValue("openInterestAbove", str(min_open_interest)))

        scanner.scannerSettingPairs = filter_options
        scanner.numberOfRows = 50

        # Request scanner data
        scan_data = await client.ib.reqScannerDataAsync(scanner)

        results = []
        for item in scan_data:
            contract = item.contractDetails.contract

            # Get option details
            ticker = client.ib.reqMktData(contract)
            await asyncio.sleep(0.2)

            result = {
                "rank": item.rank,
                "symbol": contract.symbol,
                "underlying": contract.symbol,
                "strike": contract.strike,
                "right": contract.right,
                "expiry": contract.lastTradeDateOrContractMonth,
                "volume": ticker.volume if ticker.volume else 0,
                "open_interest": ticker.openInterest if hasattr(ticker, 'openInterest') else 0,
                "implied_vol": ticker.impliedVolatility if hasattr(ticker, 'impliedVolatility') else 0
            }

            if ticker.marketPrice() and ticker.marketPrice() > 0:
                result["price"] = ticker.marketPrice()
                result["bid"] = ticker.bid
                result["ask"] = ticker.ask

            client.ib.cancelMktData(contract)
            results.append(result)

        return {
            "success": True,
            "scan_type": "options_volume",
            "filters": {
                "underlying": underlying,
                "min_volume": min_volume,
                "min_open_interest": min_open_interest
            },
            "result_count": len(results),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Options volume scan failed: {e}")
        raise DataError(f"Options volume scan failed: {e}")
