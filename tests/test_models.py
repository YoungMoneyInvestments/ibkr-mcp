"""Tests for Pydantic data models."""

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ibkr_mcp.models import (
    AccountSummary,
    AlgoStrategy,
    BarData,
    BracketOrder,
    Contract,
    FuturesContract,
    MCPResponse,
    OptionChain,
    OptionContract,
    OptionRight,
    OptionSpread,
    OptionSpreadStrategy,
    Order,
    OrderAction,
    OrderBook,
    OrderStatus,
    OrderType,
    PortfolioAllocation,
    Position,
    PositionSizing,
    RiskLimits,
    RolloverInfo,
    ScannerRequest,
    ScannerResult,
    SecType,
    TickData,
    TimeInForce,
    TrailingStop,
    VaRResult,
)


# =============================================================================
# Enum Tests
# =============================================================================


class TestEnums:
    """Test enum values match IBKR protocol."""

    def test_order_action_values(self):
        assert OrderAction.BUY.value == "BUY"
        assert OrderAction.SELL.value == "SELL"

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "MKT"
        assert OrderType.LIMIT.value == "LMT"
        assert OrderType.STOP.value == "STP"
        assert OrderType.STOP_LIMIT.value == "STP LMT"
        assert OrderType.TRAIL.value == "TRAIL"
        assert OrderType.TRAIL_LIMIT.value == "TRAIL LIMIT"

    def test_order_status_values(self):
        assert OrderStatus.FILLED.value == "Filled"
        assert OrderStatus.CANCELLED.value == "Cancelled"
        assert OrderStatus.SUBMITTED.value == "Submitted"
        assert OrderStatus.REJECTED.value == "Rejected"
        assert OrderStatus.INACTIVE.value == "Inactive"

    def test_time_in_force_values(self):
        assert TimeInForce.DAY.value == "DAY"
        assert TimeInForce.GTC.value == "GTC"
        assert TimeInForce.IOC.value == "IOC"
        assert TimeInForce.GTD.value == "GTD"

    def test_sec_type_values(self):
        assert SecType.STOCK.value == "STK"
        assert SecType.OPTION.value == "OPT"
        assert SecType.FUTURE.value == "FUT"
        assert SecType.FOREX.value == "CASH"
        assert SecType.INDEX.value == "IND"
        assert SecType.CFD.value == "CFD"
        assert SecType.BOND.value == "BOND"
        assert SecType.WARRANT.value == "WAR"
        assert SecType.COMMODITY.value == "CMDTY"

    def test_algo_strategy_values(self):
        assert AlgoStrategy.VWAP.value == "Vwap"
        assert AlgoStrategy.TWAP.value == "Twap"
        assert AlgoStrategy.ADAPTIVE.value == "Adaptive"

    def test_option_right_values(self):
        assert OptionRight.CALL.value == "C"
        assert OptionRight.PUT.value == "P"

    def test_option_spread_strategy_values(self):
        assert OptionSpreadStrategy.BULL_CALL.value == "bull_call"
        assert OptionSpreadStrategy.IRON_CONDOR.value == "iron_condor"
        assert OptionSpreadStrategy.STRADDLE.value == "straddle"


# =============================================================================
# Contract Model Tests
# =============================================================================


class TestContract:
    """Test Contract model."""

    def test_minimal_contract(self):
        c = Contract(symbol="AAPL", sec_type=SecType.STOCK)
        assert c.symbol == "AAPL"
        assert c.sec_type == SecType.STOCK
        assert c.exchange == "SMART"
        assert c.currency == "USD"

    def test_option_contract(self):
        c = Contract(
            symbol="AAPL",
            sec_type=SecType.OPTION,
            strike=Decimal("150.00"),
            right=OptionRight.CALL,
            expiry="20260320",
        )
        assert c.strike == Decimal("150.00")
        assert c.right == OptionRight.CALL
        assert c.expiry == "20260320"

    def test_futures_contract(self):
        c = Contract(
            symbol="ES",
            sec_type=SecType.FUTURE,
            exchange="CME",
            last_trade_date="20260320",
            multiplier=50.0,
        )
        assert c.last_trade_date == "20260320"
        assert c.multiplier == 50.0

    def test_missing_required_symbol_raises(self):
        with pytest.raises(ValidationError):
            Contract(sec_type=SecType.STOCK)

    def test_missing_required_sec_type_raises(self):
        with pytest.raises(ValidationError):
            Contract(symbol="AAPL")

    def test_optional_fields_default_none(self):
        c = Contract(symbol="AAPL", sec_type=SecType.STOCK)
        assert c.local_symbol is None
        assert c.con_id is None
        assert c.strike is None
        assert c.right is None


# =============================================================================
# Order Model Tests
# =============================================================================


class TestOrder:
    """Test Order model and validators."""

    def test_market_order(self):
        order = Order(
            action=OrderAction.BUY,
            total_quantity=Decimal("100"),
            order_type=OrderType.MARKET,
        )
        assert order.action == OrderAction.BUY
        assert order.total_quantity == Decimal("100")
        assert order.order_type == OrderType.MARKET
        assert order.time_in_force == TimeInForce.DAY

    def test_limit_order(self):
        order = Order(
            action=OrderAction.SELL,
            total_quantity=Decimal("50"),
            order_type=OrderType.LIMIT,
            lmt_price=Decimal("150.50"),
        )
        assert order.lmt_price == Decimal("150.50")

    def test_validate_quantity_positive(self):
        order = Order(
            action=OrderAction.BUY,
            total_quantity=Decimal("1"),
            order_type=OrderType.MARKET,
        )
        assert order.total_quantity == Decimal("1")

    def test_validate_quantity_zero_raises(self):
        with pytest.raises(ValidationError, match="Quantity must be positive"):
            Order(
                action=OrderAction.BUY,
                total_quantity=Decimal("0"),
                order_type=OrderType.MARKET,
            )

    def test_validate_quantity_negative_raises(self):
        with pytest.raises(ValidationError, match="Quantity must be positive"):
            Order(
                action=OrderAction.BUY,
                total_quantity=Decimal("-10"),
                order_type=OrderType.MARKET,
            )

    def test_fractional_quantity(self):
        order = Order(
            action=OrderAction.BUY,
            total_quantity=Decimal("0.5"),
            order_type=OrderType.MARKET,
        )
        assert order.total_quantity == Decimal("0.5")

    def test_optional_fields_default(self):
        order = Order(
            action=OrderAction.BUY,
            total_quantity=Decimal("10"),
            order_type=OrderType.MARKET,
        )
        assert order.order_id is None
        assert order.client_id is None
        assert order.lmt_price is None
        assert order.outside_rth is False
        assert order.hidden is False
        assert order.algo_strategy is None

    def test_algo_order(self):
        order = Order(
            action=OrderAction.BUY,
            total_quantity=Decimal("100"),
            order_type=OrderType.LIMIT,
            lmt_price=Decimal("150"),
            algo_strategy=AlgoStrategy.VWAP,
            algo_params={"maxPctVol": "0.1"},
        )
        assert order.algo_strategy == AlgoStrategy.VWAP
        assert order.algo_params == {"maxPctVol": "0.1"}

    def test_missing_action_raises(self):
        with pytest.raises(ValidationError):
            Order(total_quantity=Decimal("10"), order_type=OrderType.MARKET)

    def test_missing_order_type_raises(self):
        with pytest.raises(ValidationError):
            Order(action=OrderAction.BUY, total_quantity=Decimal("10"))


class TestBracketOrder:
    """Test BracketOrder model."""

    def test_basic_bracket(self):
        bo = BracketOrder(
            symbol="AAPL",
            action=OrderAction.BUY,
            quantity=100,
            entry_price=150.0,
            profit_target=160.0,
            stop_loss=145.0,
        )
        assert bo.symbol == "AAPL"
        assert bo.sec_type == SecType.STOCK
        assert bo.exchange == "SMART"

    def test_futures_bracket(self):
        bo = BracketOrder(
            symbol="ES",
            action=OrderAction.BUY,
            quantity=1,
            entry_price=5000.0,
            profit_target=5050.0,
            stop_loss=4950.0,
            sec_type=SecType.FUTURE,
            exchange="CME",
        )
        assert bo.sec_type == SecType.FUTURE
        assert bo.exchange == "CME"


class TestTrailingStop:
    """Test TrailingStop model."""

    def test_trail_amount(self):
        ts = TrailingStop(
            symbol="AAPL",
            action=OrderAction.SELL,
            quantity=100,
            trail_amount=5.0,
        )
        assert ts.trail_amount == 5.0
        assert ts.trail_percent is None

    def test_trail_percent(self):
        ts = TrailingStop(
            symbol="AAPL",
            action=OrderAction.SELL,
            quantity=100,
            trail_percent=2.0,
        )
        assert ts.trail_percent == 2.0
        assert ts.trail_amount is None


# =============================================================================
# Position & Account Model Tests
# =============================================================================


class TestPosition:
    """Test Position model."""

    def test_position_creation(self):
        contract = Contract(symbol="AAPL", sec_type=SecType.STOCK)
        pos = Position(
            account="DU12345",
            contract=contract,
            position=Decimal("100"),
            avg_cost=Decimal("150.00"),
        )
        assert pos.account == "DU12345"
        assert pos.position == Decimal("100")
        assert pos.market_price is None

    def test_position_with_pnl(self):
        contract = Contract(symbol="AAPL", sec_type=SecType.STOCK)
        pos = Position(
            account="DU12345",
            contract=contract,
            position=Decimal("100"),
            avg_cost=Decimal("150.00"),
            market_price=Decimal("155.00"),
            unrealized_pnl=Decimal("500.00"),
        )
        assert pos.unrealized_pnl == Decimal("500.00")


class TestAccountSummary:
    """Test AccountSummary model."""

    def test_creation(self):
        summary = AccountSummary(
            account="DU12345",
            tag="NetLiquidation",
            value="100000.00",
            currency="USD",
        )
        assert summary.tag == "NetLiquidation"
        assert summary.value == "100000.00"


class TestPortfolioAllocation:
    """Test PortfolioAllocation model."""

    def test_creation(self):
        alloc = PortfolioAllocation(
            total_value=100000.0,
            by_asset_class={"STK": {"value": 80000, "pct": 80}},
            by_symbol={"AAPL": {"value": 50000, "pct": 50}},
            by_currency={"USD": {"value": 100000, "pct": 100}},
            position_count=5,
        )
        assert alloc.total_value == 100000.0
        assert alloc.position_count == 5


# =============================================================================
# Market Data Model Tests
# =============================================================================


class TestTickData:
    """Test TickData model."""

    def test_minimal(self):
        tick = TickData(symbol="AAPL")
        assert tick.symbol == "AAPL"
        assert tick.bid is None
        assert tick.ask is None
        assert isinstance(tick.timestamp, datetime)

    def test_full_tick(self):
        tick = TickData(
            symbol="AAPL",
            bid=149.90,
            ask=150.10,
            last=150.00,
            volume=1000000,
            high=151.0,
            low=148.5,
        )
        assert tick.bid == 149.90
        assert tick.ask == 150.10


class TestBarData:
    """Test BarData model."""

    def test_creation(self):
        now = datetime.now()
        bar = BarData(
            date=now,
            open=150.0,
            high=152.0,
            low=149.0,
            close=151.5,
            volume=500000,
        )
        assert bar.open == 150.0
        assert bar.close == 151.5
        assert bar.average is None

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            BarData(date=datetime.now(), open=150.0)


class TestOrderBook:
    """Test OrderBook model."""

    def test_creation(self):
        now = datetime.now()
        ob = OrderBook(
            symbol="AAPL",
            bids=[{"price": 149.90, "size": 100}],
            asks=[{"price": 150.10, "size": 200}],
            spread=0.20,
            mid_price=150.0,
            imbalance=-0.33,
            timestamp=now,
        )
        assert ob.spread == 0.20
        assert len(ob.bids) == 1


# =============================================================================
# Options Model Tests
# =============================================================================


class TestOptionContract:
    """Test OptionContract model."""

    def test_call_option(self):
        opt = OptionContract(
            symbol="AAPL",
            expiry="20260320",
            strike=150.0,
            right=OptionRight.CALL,
            delta=0.55,
            theta=-0.05,
        )
        assert opt.right == OptionRight.CALL
        assert opt.delta == 0.55

    def test_put_option(self):
        opt = OptionContract(
            symbol="AAPL",
            expiry="20260320",
            strike=150.0,
            right=OptionRight.PUT,
        )
        assert opt.right == OptionRight.PUT


class TestOptionChain:
    """Test OptionChain model."""

    def test_creation(self):
        chain = OptionChain(
            symbol="AAPL",
            underlying_price=150.0,
            expirations=["20260320", "20260417"],
            options=[],
        )
        assert len(chain.expirations) == 2
        assert chain.options == []


class TestOptionSpread:
    """Test OptionSpread model."""

    def test_bull_call(self):
        spread = OptionSpread(
            strategy=OptionSpreadStrategy.BULL_CALL,
            symbol="AAPL",
            underlying_price=150.0,
            legs=[
                {"strike": 145, "right": "C", "action": "BUY"},
                {"strike": 155, "right": "C", "action": "SELL"},
            ],
            total_cost=3.50,
            max_profit=6.50,
            max_loss=3.50,
            breakeven=[148.50],
        )
        assert spread.strategy == OptionSpreadStrategy.BULL_CALL
        assert len(spread.legs) == 2


# =============================================================================
# Futures Model Tests
# =============================================================================


class TestFuturesContract:
    """Test FuturesContract model."""

    def test_creation(self):
        fc = FuturesContract(
            symbol="ES",
            local_symbol="ESH6",
            con_id=12345,
            last_trade_date="20260320",
            multiplier=50.0,
            exchange="CME",
        )
        assert fc.symbol == "ES"
        assert fc.is_front_month is False
        assert fc.is_continuous is False

    def test_front_month(self):
        fc = FuturesContract(
            symbol="ES",
            local_symbol="ESH6",
            con_id=12345,
            last_trade_date="20260320",
            multiplier=50.0,
            exchange="CME",
            is_front_month=True,
        )
        assert fc.is_front_month is True


class TestRolloverInfo:
    """Test RolloverInfo model."""

    def test_no_rollover_needed(self):
        ri = RolloverInfo(rollover_needed=False)
        assert ri.current_contract is None
        assert ri.recommendation is None

    def test_rollover_needed(self):
        fc = FuturesContract(
            symbol="ES",
            local_symbol="ESH6",
            con_id=12345,
            last_trade_date="20260320",
            multiplier=50.0,
            exchange="CME",
        )
        ri = RolloverInfo(
            rollover_needed=True,
            current_contract=fc,
            days_to_expiry=5,
            recommendation="Roll to next month",
        )
        assert ri.rollover_needed is True
        assert ri.days_to_expiry == 5


# =============================================================================
# Scanner Model Tests
# =============================================================================


class TestScannerResult:
    """Test ScannerResult model."""

    def test_creation(self):
        sr = ScannerResult(
            rank=1,
            symbol="AAPL",
            sec_type="STK",
            exchange="SMART",
            currency="USD",
            current_price=150.0,
            volume=1000000,
        )
        assert sr.rank == 1
        assert sr.current_price == 150.0


class TestScannerRequest:
    """Test ScannerRequest model."""

    def test_defaults(self):
        req = ScannerRequest(scan_code="TOP_PERC_GAIN")
        assert req.location == "STK.US.MAJOR"
        assert req.instrument == "STK"
        assert req.num_rows == 50
        assert req.filters is None

    def test_custom(self):
        req = ScannerRequest(
            scan_code="HOT_BY_VOLUME",
            location="STK.US",
            num_rows=10,
            filters={"priceAbove": 5.0},
        )
        assert req.num_rows == 10
        assert req.filters["priceAbove"] == 5.0


# =============================================================================
# Risk Model Tests
# =============================================================================


class TestPositionSizing:
    """Test PositionSizing model."""

    def test_creation(self):
        ps = PositionSizing(
            symbol="AAPL",
            method="fixed_risk",
            position_size=66,
            entry_price=150.0,
            stop_loss=145.0,
            risk_amount=330.0,
            total_value=9900.0,
            risk_per_share=5.0,
            risk_percentage=1.0,
        )
        assert ps.position_size == 66
        assert ps.risk_per_share == 5.0


class TestRiskLimits:
    """Test RiskLimits model."""

    def test_creation(self):
        rl = RiskLimits(
            overall_status="OK",
            net_liquidation=100000.0,
            margin_utilization={"current": 30.0, "limit": 50.0},
            concentration_risk={"max": 15.0, "limit": 20.0},
            buying_power={"available": 200000.0},
            largest_position={"symbol": "AAPL", "pct": 15.0},
        )
        assert rl.overall_status == "OK"


class TestVaRResult:
    """Test VaRResult model."""

    def test_creation(self):
        var = VaRResult(
            portfolio_value=100000.0,
            confidence_level=0.95,
            time_horizon_days=1,
            parametric_var={"var": 2500.0, "pct": 2.5},
            historical_var={"var": 2800.0, "pct": 2.8},
            interpretation="95% confidence 1-day VaR",
        )
        assert var.confidence_level == 0.95


# =============================================================================
# Response Model Tests
# =============================================================================


class TestMCPResponse:
    """Test MCPResponse model."""

    def test_success_response(self):
        resp = MCPResponse(
            success=True,
            message="Order placed",
            data={"order_id": 123},
        )
        assert resp.success is True
        assert resp.error is None
        assert isinstance(resp.timestamp, datetime)

    def test_error_response(self):
        resp = MCPResponse(
            success=False,
            error="Connection failed",
        )
        assert resp.success is False
        assert resp.error == "Connection failed"

    def test_serialization_roundtrip(self):
        resp = MCPResponse(success=True, message="ok")
        data = resp.model_dump()
        assert data["success"] is True
        assert "timestamp" in data
