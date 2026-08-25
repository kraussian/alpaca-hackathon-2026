import datetime as dt

import pytest

from agent_pkg.audit import AuditLog
from agent_pkg.broker import Broker
from agent_pkg.gates import Limits, VerticalOrder

DEV_KEY = "PKDEVKEY0123456789ABCDEF12"


class FakeTradingClient:
    """Stands in for alpaca-py. Records what would have been submitted."""

    def __init__(self):
        self.submitted = []
        self.closed = []

    def submit_order(self, request):
        self.submitted.append(request)
        return type("Order", (), {"id": "fake-order-id"})()

    def close_position(self, symbol):
        self.closed.append(symbol)


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
