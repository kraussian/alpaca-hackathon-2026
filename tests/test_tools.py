"""The model-facing tool layer.

Verified live against the dev account on 2026-08-25, but a check that only
exists in a scratch script is a check that stops running. These pin the same
behaviour with no network.
"""

import asyncio
import datetime as dt

from agent_pkg import tools
from agent_pkg.audit import AuditLog
from agent_pkg.broker import Broker
from agent_pkg.gates import Limits
from tests.test_broker import FakeOptionData, FakeStockData

DEV_KEY = "PKDEVKEY0123456789ABCDEF12"

VALID = {
    "underlying": "SPY",
    "expiry": "2026-09-18",
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


class FakeTradingClient:
    def __init__(self):
        self.submitted = []
        self.closed = []

    def submit_order(self, request):
        self.submitted.append(request)
        return type("Order", (), {"id": "fake-order-id"})()

    def close_position(self, symbol):
        self.closed.append(symbol)


def make_broker(tmp_path, monkeypatch, max_orders=5):
    monkeypatch.setenv("ALPACA_PAPER_TRADE", "true")
    monkeypatch.setenv("ALPACA_ACCOUNT_ROLE", "dev")
    monkeypatch.setenv("DEV_API_KEY", DEV_KEY)
    monkeypatch.setenv("DEV_SECRET_KEY", "devsecret")
    broker = Broker(
        limits=Limits(),
        audit=AuditLog(session_id="tools-test", directory=tmp_path),
        kill_file=tmp_path / ".kill",
        client=FakeTradingClient(),
        clock_is_open=True,
        now=dt.datetime(2026, 8, 25, 14, 0, tzinfo=dt.UTC),
        option_data=FakeOptionData({}),
        stock_data=FakeStockData({"SPY": 765.0}),
    )
    tools.bind(broker, max_orders)
    return broker


def test_valid_order_is_submitted(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch)
    result = asyncio.run(tools.open_vertical(**VALID))
    assert result.startswith("SUBMITTED")
    assert len(broker.client.submitted) == 1


def test_kill_switch_blocks_open_and_nothing_is_submitted(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch)
    broker.kill_file.write_text("stop", encoding="utf-8")
    result = asyncio.run(tools.open_vertical(**VALID))
    assert result.startswith("VETO")
    assert "kill switch" in result
    assert broker.client.submitted == []


def test_kill_switch_blocks_close(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch)
    broker.kill_file.write_text("stop", encoding="utf-8")
    result = asyncio.run(
        tools.close_vertical(VALID["long_symbol"], VALID["short_symbol"])
    )
    assert result.startswith("VETO")
    assert broker.client.closed == []


def test_session_order_cap_is_enforced_independently_of_the_gates(
    tmp_path, monkeypatch
):
    broker = make_broker(tmp_path, monkeypatch, max_orders=1)
    first = asyncio.run(tools.open_vertical(**VALID))
    assert first.startswith("SUBMITTED")
    # a second, otherwise-identical order is stopped by the session cap
    second = asyncio.run(tools.open_vertical(**VALID))
    assert second.startswith("VETO")
    assert "order cap" in second
    assert len(broker.client.submitted) == 1


def test_engage_kill_switch_stops_subsequent_orders(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch)
    asyncio.run(tools.engage_kill_switch("account state looks wrong"))
    assert broker.kill_file.exists()
    result = asyncio.run(tools.open_vertical(**VALID))
    assert result.startswith("VETO")
    assert broker.client.submitted == []


def test_unparseable_expiry_is_vetoed_not_raised(tmp_path, monkeypatch):
    broker = make_broker(tmp_path, monkeypatch)
    result = asyncio.run(tools.open_vertical(**{**VALID, "expiry": "next friday"}))
    assert result.startswith("VETO")
    assert broker.client.submitted == []
