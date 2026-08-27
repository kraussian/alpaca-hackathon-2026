import datetime as dt

import pytest

from agent_pkg.audit import AuditLog
from agent_pkg.broker import Broker
from agent_pkg.gates import Limits, VerticalOrder

DEV_KEY = "PKDEVKEY0123456789ABCDEF12"


class FakeStockData:
    """Serves a quote whose midpoint is the price the tests expect."""

    def __init__(self, prices):
        self.prices = prices

    def get_stock_latest_quote(self, request):
        return {
            s: type("Q", (), {"bid_price": p - 0.01, "ask_price": p + 0.01})()
            for s, p in self.prices.items()
        }

    def get_stock_latest_trade(self, request):
        return {s: type("T", (), {"price": p})() for s, p in self.prices.items()}


class FakeOptionData:
    """Mimics the alpaca-py snapshot shape: greeks is an object, not a dict."""

    def __init__(self, deltas):
        self.deltas = deltas

    def get_option_snapshot(self, request):
        return {
            s: type("Snap", (), {"greeks": type("G", (), {"delta": d})()})()
            for s, d in self.deltas.items()
        }


class FakeTradingClient:
    """Stands in for alpaca-py. Records what would have been submitted."""

    def __init__(self, positions=None):
        self.submitted = []
        self.closed = []
        self.positions = positions or []

    def submit_order(self, request):
        self.submitted.append(request)
        return type("Order", (), {"id": "fake-order-id"})()

    def close_position(self, symbol):
        self.closed.append(symbol)

    def get_all_positions(self):
        return self.positions


def make_order(**over):
    base = {
        "underlying": "SPY",
        "expiry": dt.date(2026, 9, 18),
        "option_type": "call",
        "long_symbol": "SPY260918C00760000",
        "short_symbol": "SPY260918C00765000",
        "long_strike": 760.0,
        "short_strike": 765.0,
        "long_ask": 12.00,
        "short_bid": 9.50,
        "qty": 1,
        "long_delta": 0.55,
        "short_delta": 0.45,
        "short_iv": 0.18,
        "underlying_price": 765.0,
    }
    base.update(over)
    return VerticalOrder(**base)


def make_broker(tmp_path, monkeypatch, **over):
    monkeypatch.setenv("ALPACA_PAPER_TRADE", over.pop("paper_env", "true"))
    monkeypatch.setenv("ALPACA_ACCOUNT_ROLE", over.pop("role", "dev"))
    monkeypatch.setenv("DEV_API_KEY", over.pop("key", DEV_KEY))
    monkeypatch.setenv("DEV_SECRET_KEY", "devsecret")
    return Broker(
        limits=Limits(),
        audit=AuditLog(session_id="test", directory=tmp_path),
        kill_file=tmp_path / ".kill",
        client=FakeTradingClient(),
        clock_is_open=over.pop("clock_is_open", True),
        now=over.pop("now", dt.datetime(2026, 8, 25, 14, 0, tzinfo=dt.UTC)),
        option_data=FakeOptionData({}),
        stock_data=FakeStockData(over.pop("prices", {"SPY": 765.0})),
    )


def test_broker_refuses_to_construct_when_not_paper(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="paper"):
        make_broker(tmp_path, monkeypatch, paper_env="false")


def test_broker_refuses_the_competition_account_before_kickoff(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "PKCOMPKEY0123456789ABCDE12")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "compsecret")
    with pytest.raises(RuntimeError, match="kickoff"):
        make_broker(tmp_path, monkeypatch, role="competition")


def test_broker_refuses_an_unset_role(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_ACCOUNT_ROLE", raising=False)
    with pytest.raises(RuntimeError, match="ALPACA_ACCOUNT_ROLE"):
        Broker(
            limits=Limits(),
            audit=AuditLog(session_id="test", directory=tmp_path),
            kill_file=tmp_path / ".kill",
            client=FakeTradingClient(),
            clock_is_open=True,
        )


def test_open_vertical_submits_when_gates_allow(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch)
    result = broker.open_vertical(make_order())
    assert result["submitted"] is True
    assert result["order_id"] == "fake-order-id"
    assert len(broker.client.submitted) == 1


def test_open_vertical_does_not_submit_when_a_gate_vetoes(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch)
    result = broker.open_vertical(make_order(qty=99))
    assert result["submitted"] is False
    assert result["reasons"]
    assert broker.client.submitted == []


def test_kill_file_blocks_submission(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch)
    broker.kill_file.write_text("stop", encoding="utf-8")
    result = broker.open_vertical(make_order())
    assert result["submitted"] is False
    assert any("kill switch" in r for r in result["reasons"])
    assert broker.client.submitted == []


def test_veto_is_written_to_the_audit_log(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch)
    broker.open_vertical(make_order(qty=99))
    written = broker.audit.path.read_text(encoding="utf-8")
    assert "gate_verdict" in written
    assert "contracts" in written


def test_close_vertical_closes_the_short_leg_first(tmp_path, monkeypatch):
    """Closing the long leg first leaves the short leg uncovered, and Alpaca
    rejects it: level 3 cannot hold a naked short call. Measured 2026-08-25."""
    broker = make_broker(tmp_path, monkeypatch)
    o = make_order()
    broker.close_vertical(o.long_symbol, o.short_symbol)
    assert broker.client.closed == [o.short_symbol, o.long_symbol]


def test_close_vertical_is_blocked_by_the_kill_switch(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch)
    broker.kill_file.write_text("stop", encoding="utf-8")
    o = make_order()
    result = broker.close_vertical(o.long_symbol, o.short_symbol)
    assert result["submitted"] is False
    assert broker.client.closed == []


def test_opening_records_the_position_for_later_gates(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch)
    broker.open_vertical(make_order())
    snap = broker.snapshot()
    assert len(snap.open_positions) == 1
    assert snap.open_positions[0].worst_case_loss == pytest.approx(250.0)


class FakePosition:
    def __init__(self, symbol, qty, avg_entry_price):
        from alpaca.trading.enums import AssetClass

        self.symbol = symbol
        self.qty = qty
        self.avg_entry_price = avg_entry_price
        self.asset_class = AssetClass.US_OPTION


def make_loading_broker(tmp_path, monkeypatch, positions, deltas, prices=None):
    monkeypatch.setenv("ALPACA_PAPER_TRADE", "true")
    monkeypatch.setenv("ALPACA_ACCOUNT_ROLE", "dev")
    monkeypatch.setenv("DEV_API_KEY", DEV_KEY)
    monkeypatch.setenv("DEV_SECRET_KEY", "devsecret")
    return Broker(
        limits=Limits(),
        audit=AuditLog(session_id="test", directory=tmp_path),
        kill_file=tmp_path / ".kill",
        client=FakeTradingClient(positions=positions),
        clock_is_open=True,
        now=dt.datetime(2026, 8, 26, 14, 0, tzinfo=dt.UTC),
        option_data=FakeOptionData(deltas),
        stock_data=FakeStockData(prices or {"QQQ": 710.73}),
    )


# The dev account's real book on 2026-08-26: a QQQ Sep-18 745/750 call credit
# spread, three lots, filled at 2.62 / 1.93.
LIVE_BOOK = [
    FakePosition("QQQ260918C00745000", "-3", "2.62"),
    FakePosition("QQQ260918C00750000", "3", "1.93"),
]
LIVE_DELTAS = {"QQQ260918C00745000": 0.1463, "QQQ260918C00750000": 0.1089}


def test_load_open_positions_prices_the_live_book(tmp_path, monkeypatch):
    broker = make_loading_broker(tmp_path, monkeypatch, LIVE_BOOK, LIVE_DELTAS)
    (pos,) = broker.load_open_positions()
    assert pos.key == "QQQ:20260918:call:745-750"
    assert pos.worst_case_loss == pytest.approx(1293.0)
    assert pos.net_delta_notional == pytest.approx(-7974.39, abs=0.01)
    # And it reaches the gates, which is the whole point.
    assert broker.snapshot().open_positions == (pos,)


def test_load_open_positions_on_an_empty_account(tmp_path, monkeypatch):
    broker = make_loading_broker(tmp_path, monkeypatch, [], {})
    assert broker.load_open_positions() == ()


def test_load_refuses_when_a_delta_is_missing(tmp_path, monkeypatch):
    """Substituting zero would leave the book delta gate quietly under-counting."""
    broker = make_loading_broker(
        tmp_path, monkeypatch, LIVE_BOOK, {s: None for s in LIVE_DELTAS}
    )
    with pytest.raises(RuntimeError, match="no delta available"):
        broker.load_open_positions()


def test_loaded_book_is_written_to_the_audit_log(tmp_path, monkeypatch):
    broker = make_loading_broker(tmp_path, monkeypatch, LIVE_BOOK, LIVE_DELTAS)
    broker.load_open_positions()
    written = broker.audit.path.read_text(encoding="utf-8")
    assert "book_loaded" in written
    assert "QQQ:20260918:call:745-750" in written


def test_closing_resyncs_the_book_from_the_broker(tmp_path, monkeypatch):
    """A hand-maintained list would drop a position whose close never filled."""
    broker = make_loading_broker(tmp_path, monkeypatch, LIVE_BOOK, LIVE_DELTAS)
    broker.load_open_positions()
    assert len(broker.snapshot().open_positions) == 1
    # The close is submitted but the fake account still reports the legs, as a
    # real one would until the order fills.
    broker.close_vertical("QQQ260918C00750000", "QQQ260918C00745000")
    assert broker.client.closed == ["QQQ260918C00745000", "QQQ260918C00750000"]
    assert len(broker.snapshot().open_positions) == 1


# The real discrepancy that prompted this: QQQ printed 717.80 on a thin
# pre-market trade while the quote sat at 712.34/712.44, and the option
# chain's greeks were struck off the quote. Measured 2026-08-27.
def test_the_gate_uses_the_quote_midpoint_not_the_supplied_price(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch, prices={"SPY": 700.0})
    # The model supplies 765; the book says 700.
    broker.open_vertical(make_order(underlying_price=765.0))
    (submitted,) = broker.snapshot().open_positions
    # net delta 0.10 * 100 * 1 * 700, not * 765.
    assert submitted.net_delta_notional == pytest.approx(0.10 * 100 * 700.0)


def test_a_corrected_underlying_price_is_recorded(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch, prices={"SPY": 700.0})
    broker.open_vertical(make_order(underlying_price=765.0))
    written = broker.audit.path.read_text(encoding="utf-8")
    assert "underlying_price_corrected" in written
    assert "765" in written and "700" in written


def test_a_matching_price_is_not_recorded_as_a_correction(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch, prices={"SPY": 765.0})
    broker.open_vertical(make_order(underlying_price=765.0))
    assert "underlying_price_corrected" not in broker.audit.path.read_text(
        encoding="utf-8"
    )


def test_a_wrong_ticker_price_cannot_hide_directional_exposure(tmp_path, monkeypatch):
    """Passing another allowlisted name's price used to move the delta figure.

    IWM trades near 299 and SPY near 765. Supplying IWM's price on an SPY
    spread understated the book delta by a factor of two and a half, and
    nothing checked it.
    """
    limits = Limits(max_net_delta_notional=5000.0)
    broker = make_broker(tmp_path, monkeypatch, prices={"SPY": 765.0})
    broker.limits = limits
    result = broker.open_vertical(make_order(qty=1, underlying_price=299.0))
    assert result["submitted"] is False
    assert any("book net delta" in r for r in result["reasons"])


class NoQuoteStockData:
    def get_stock_latest_quote(self, request):
        raise KeyError("no quote")


def test_an_unreadable_quote_vetoes_rather_than_trusting_the_model(
    tmp_path, monkeypatch
):
    broker = make_broker(tmp_path, monkeypatch)
    broker.stock_data = NoQuoteStockData()
    result = broker.open_vertical(make_order())
    assert result["submitted"] is False
    assert any("could not read a live quote" in r for r in result["reasons"])
    assert broker.client.submitted == []


def test_a_crossed_quote_is_not_used(tmp_path, monkeypatch):
    """A crossed book is stale or broken; its midpoint is not a price."""
    broker = make_broker(tmp_path, monkeypatch)
    broker.stock_data = type(
        "Crossed",
        (),
        {
            "get_stock_latest_quote": lambda self, r: {
                "SPY": type("Q", (), {"bid_price": 766.0, "ask_price": 764.0})()
            }
        },
    )()
    result = broker.open_vertical(make_order())
    assert result["submitted"] is False
    assert any("could not read a live quote" in r for r in result["reasons"])
