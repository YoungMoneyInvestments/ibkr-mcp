"""
Pydantic models for IBKR MCP Server data structures.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Enums
# =============================================================================


class OrderAction(str, Enum):
    """Order action types."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order types."""
    MARKET = "MKT"
    LIMIT = "LMT"
    STOP = "STP"
    STOP_LIMIT = "STP LMT"
    TRAIL = "TRAIL"
    TRAIL_LIMIT = "TRAIL LIMIT"


class OrderStatus(str, Enum):
    """Order status types."""
    PENDING_SUBMIT = "PendingSubmit"
    PENDING_CANCEL = "PendingCancel"
    PRE_SUBMITTED = "PreSubmitted"
    SUBMITTED = "Submitted"
    CANCELLED = "Cancelled"
    FILLED = "Filled"
    INACTIVE = "Inactive"
    PENDING_REJECT = "PendingReject"
    REJECTED = "Rejected"


class TimeInForce(str, Enum):
    """Time in force types."""
    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"
    GTD = "GTD"


class SecType(str, Enum):
    """Security types."""
    STOCK = "STK"
    OPTION = "OPT"
    FUTURE = "FUT"
    FOREX = "CASH"
    INDEX = "IND"
    CFD = "CFD"
    BOND = "BOND"
    WARRANT = "WAR"
    COMMODITY = "CMDTY"


class AlgoStrategy(str, Enum):
    """IBKR algorithmic order strategies."""
    ARRIVAL_PRICE = "ArrivalPx"
    DARK_ICE = "DarkIce"
    PCT_VOL = "PctVol"
    TWAP = "Twap"
    VWAP = "Vwap"
    ACCUMULATE_DISTRIBUTE = "AD"
    BALANCE_IMPACT_RISK = "BalanceImpactRisk"
    MIN_IMPACT = "MinImpact"
    ADAPTIVE = "Adaptive"


class OptionRight(str, Enum):
    """Option right (call/put)."""
    CALL = "C"
    PUT = "P"


class OptionSpreadStrategy(str, Enum):
    """Option spread strategies."""
    BULL_CALL = "bull_call"
    BEAR_PUT = "bear_put"
    BULL_PUT = "bull_put"
    BEAR_CALL = "bear_call"
    STRADDLE = "straddle"
    STRANGLE = "strangle"
    IRON_CONDOR = "iron_condor"


# =============================================================================
# Contract Models
# =============================================================================


class Contract(BaseModel):
    """Contract information."""

    symbol: str = Field(..., description="Contract symbol")
    sec_type: SecType = Field(..., description="Security type")
    exchange: str = Field(default="SMART", description="Exchange")
    currency: str = Field(default="USD", description="Currency")
    local_symbol: Optional[str] = Field(None, description="Local symbol")
    con_id: Optional[int] = Field(None, description="Contract ID")

    # Options specific
    strike: Optional[Decimal] = Field(None, description="Strike price for options")
    right: Optional[OptionRight] = Field(None, description="Right (C/P) for options")
    expiry: Optional[str] = Field(None, description="Expiry date")

    # Futures specific
    last_trade_date: Optional[str] = Field(None, description="Last trade date for futures")
    multiplier: Optional[float] = Field(None, description="Contract multiplier")
    trading_class: Optional[str] = Field(None, description="Trading class")


# =============================================================================
# Order Models
# =============================================================================


class Order(BaseModel):
    """Order information."""

    order_id: Optional[int] = Field(None, description="Order ID")
    client_id: Optional[int] = Field(None, description="Client ID")
    action: OrderAction = Field(..., description="Order action (BUY/SELL)")
    total_quantity: Decimal = Field(..., description="Total quantity")
    order_type: OrderType = Field(..., description="Order type")
    lmt_price: Optional[Decimal] = Field(None, description="Limit price")
    aux_price: Optional[Decimal] = Field(None, description="Auxiliary price (stop price)")
    time_in_force: TimeInForce = Field(default=TimeInForce.DAY, description="Time in force")

    # Optional parameters
    good_after_time: Optional[str] = Field(None, description="Good after time")
    good_till_date: Optional[str] = Field(None, description="Good till date")
    outside_rth: bool = Field(default=False, description="Allow outside regular trading hours")
    hidden: bool = Field(default=False, description="Hidden order")

    # OCA (One-Cancels-All) parameters
    oca_group: Optional[str] = Field(None, description="OCA group name")
    oca_type: Optional[int] = Field(None, description="OCA type (1=cancel, 2=reduce, 3=reduce+overfill)")

    # Algo parameters
    algo_strategy: Optional[AlgoStrategy] = Field(None, description="Algo strategy")
    algo_params: Optional[Dict[str, str]] = Field(None, description="Algo parameters")

    @field_validator("total_quantity")
    @classmethod
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be positive")
        return v


class BracketOrder(BaseModel):
    """Bracket order (entry + take profit + stop loss)."""

    symbol: str
    action: OrderAction
    quantity: int
    entry_price: float
    profit_target: float
    stop_loss: float
    sec_type: SecType = SecType.STOCK
    exchange: str = "SMART"


class TrailingStop(BaseModel):
    """Trailing stop order."""

    symbol: str
    action: OrderAction
    quantity: int
    trail_amount: Optional[float] = None
    trail_percent: Optional[float] = None
    sec_type: SecType = SecType.STOCK
    exchange: str = "SMART"


# =============================================================================
# Position and Account Models
# =============================================================================


class Position(BaseModel):
    """Position information."""

    account: str = Field(..., description="Account")
    contract: Contract = Field(..., description="Contract")
    position: Decimal = Field(..., description="Position size")
    avg_cost: Decimal = Field(..., description="Average cost")
    market_price: Optional[Decimal] = Field(None, description="Current market price")
    market_value: Optional[Decimal] = Field(None, description="Market value")
    unrealized_pnl: Optional[Decimal] = Field(None, description="Unrealized P&L")
    realized_pnl: Optional[Decimal] = Field(None, description="Realized P&L")


class AccountSummary(BaseModel):
    """Account summary information."""

    account: str = Field(..., description="Account ID")
    tag: str = Field(..., description="Summary tag")
    value: str = Field(..., description="Summary value")
    currency: str = Field(..., description="Currency")


class PortfolioAllocation(BaseModel):
    """Portfolio allocation breakdown."""

    total_value: float
    by_asset_class: Dict[str, Dict[str, Any]]
    by_symbol: Dict[str, Dict[str, Any]]
    by_currency: Dict[str, Dict[str, Any]]
    position_count: int


# =============================================================================
# Market Data Models
# =============================================================================


class TickData(BaseModel):
    """Market tick data."""

    symbol: str = Field(..., description="Symbol")
    bid: Optional[float] = Field(None, description="Bid price")
    ask: Optional[float] = Field(None, description="Ask price")
    last: Optional[float] = Field(None, description="Last price")
    close: Optional[float] = Field(None, description="Close price")
    volume: Optional[int] = Field(None, description="Volume")
    high: Optional[float] = Field(None, description="High price")
    low: Optional[float] = Field(None, description="Low price")
    bid_size: Optional[int] = Field(None, description="Bid size")
    ask_size: Optional[int] = Field(None, description="Ask size")
    timestamp: datetime = Field(default_factory=datetime.now, description="Timestamp")


class BarData(BaseModel):
    """Historical bar data."""

    date: datetime = Field(..., description="Bar date/time")
    open: float = Field(..., description="Open price")
    high: float = Field(..., description="High price")
    low: float = Field(..., description="Low price")
    close: float = Field(..., description="Close price")
    volume: int = Field(..., description="Volume")
    average: Optional[float] = Field(None, description="Average price")
    bar_count: Optional[int] = Field(None, description="Trade count")


class OrderBook(BaseModel):
    """Level 2 order book data."""

    symbol: str
    bids: List[Dict[str, Any]]
    asks: List[Dict[str, Any]]
    spread: float
    mid_price: float
    imbalance: float
    timestamp: datetime


# =============================================================================
# Options Models
# =============================================================================


class OptionContract(BaseModel):
    """Option contract with Greeks."""

    symbol: str
    expiry: str
    strike: float
    right: OptionRight
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    implied_vol: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None


class OptionChain(BaseModel):
    """Option chain for an underlying."""

    symbol: str
    underlying_price: float
    expirations: List[str]
    options: List[OptionContract]


class OptionSpread(BaseModel):
    """Option spread analysis."""

    strategy: OptionSpreadStrategy
    symbol: str
    underlying_price: float
    legs: List[Dict[str, Any]]
    total_cost: float
    max_profit: float
    max_loss: float
    breakeven: List[float]


# =============================================================================
# Futures Models
# =============================================================================


class FuturesContract(BaseModel):
    """Futures contract information."""

    symbol: str
    local_symbol: str
    con_id: int
    last_trade_date: str
    multiplier: float
    exchange: str
    trading_class: Optional[str] = None
    min_tick: Optional[float] = None
    is_front_month: bool = False
    is_continuous: bool = False


class RolloverInfo(BaseModel):
    """Futures rollover information."""

    rollover_needed: bool
    current_contract: Optional[FuturesContract] = None
    next_contract: Optional[FuturesContract] = None
    days_to_expiry: Optional[int] = None
    recommendation: Optional[str] = None


# =============================================================================
# Scanner Models
# =============================================================================


class ScannerResult(BaseModel):
    """Market scanner result."""

    rank: int
    symbol: str
    sec_type: str
    exchange: str
    currency: str
    current_price: Optional[float] = None
    volume: Optional[int] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None


class ScannerRequest(BaseModel):
    """Scanner request parameters."""

    scan_code: str
    location: str = "STK.US.MAJOR"
    instrument: str = "STK"
    num_rows: int = 50
    filters: Optional[Dict[str, Any]] = None


# =============================================================================
# Risk Models
# =============================================================================


class PositionSizing(BaseModel):
    """Position sizing calculation result."""

    symbol: str
    method: str
    position_size: int
    entry_price: float
    stop_loss: float
    risk_amount: float
    total_value: float
    risk_per_share: float
    risk_percentage: float


class RiskLimits(BaseModel):
    """Risk limits check result."""

    overall_status: str  # OK, WARNING, CRITICAL
    net_liquidation: float
    margin_utilization: Dict[str, Any]
    concentration_risk: Dict[str, Any]
    buying_power: Dict[str, Any]
    largest_position: Dict[str, Any]


class VaRResult(BaseModel):
    """Value at Risk calculation result."""

    portfolio_value: float
    confidence_level: float
    time_horizon_days: int
    parametric_var: Dict[str, float]
    historical_var: Dict[str, float]
    interpretation: str


# =============================================================================
# Response Models
# =============================================================================


class MCPResponse(BaseModel):
    """Generic MCP response wrapper."""

    success: bool = Field(..., description="Success status")
    message: Optional[str] = Field(None, description="Response message")
    data: Optional[Any] = Field(None, description="Response data")
    error: Optional[str] = Field(None, description="Error message")
    timestamp: datetime = Field(default_factory=datetime.now, description="Response timestamp")
