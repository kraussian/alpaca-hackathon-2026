import datetime as dt

import pytest

from agent_pkg.gates import (
    Limits,
    OpenPosition,
    Snapshot,
    VerticalOrder,
    check_loss,
    check_structure,
    net_debit,
    quote_is_sane,
    third_friday,
    width,
    worst_case_loss,
)


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


def make_snapshot(**over):
    base = {
        "now": dt.datetime(2026, 9, 1, 15, 0, tzinfo=dt.UTC),
        "market_open": True,
        "kill_switch": False,
        "paper": True,
        "key_prefix": "PK",
        "open_positions": (),
    }
    base.update(over)
    return Snapshot(**base)


def test_third_friday_known_values():
    assert third_friday(2026, 9) == dt.date(2026, 9, 18)
    assert third_friday(2026, 8) == dt.date(2026, 8, 21)
    assert third_friday(2026, 5) == dt.date(2026, 5, 15)
    assert third_friday(2027, 1) == dt.date(2027, 1, 15)


def test_width_is_absolute():
    assert width(make_order()) == 5.0
    assert width(make_order(long_strike=765.0, short_strike=760.0)) == 5.0


def test_structure_allows_a_normal_vertical():
    assert check_structure(make_order()) == ()


def test_structure_rejects_same_strike():
    reasons = check_structure(make_order(short_strike=760.0))
    assert any("same strike" in r for r in reasons)


def test_structure_rejects_bad_option_type():
    reasons = check_structure(make_order(option_type="straddle"))
    assert any("option_type" in r for r in reasons)


def test_structure_rejects_zero_or_negative_qty():
    assert any("qty" in r for r in check_structure(make_order(qty=0)))
    assert any("qty" in r for r in check_structure(make_order(qty=-1)))


def test_structure_rejects_mismatched_symbols():
    reasons = check_structure(make_order(short_symbol="QQQ260918C00765000"))
    assert any("underlying" in r for r in reasons)


def test_limits_defaults_match_the_spec():
    lim = Limits()
    assert lim.max_contracts == 5
    assert lim.max_loss_per_position == 1500.0
    assert lim.max_aggregate_loss == 15000.0
    assert lim.min_days_to_expiry == 10
    assert lim.dedupe_minutes == 30
    assert lim.allowed_underlyings == frozenset({"SPY", "QQQ", "IWM"})


def test_net_debit_positive_for_a_debit_spread():
    # pay 12.00 for the long, receive 9.50 for the short
    assert net_debit(make_order()) == pytest.approx(2.50)


def test_net_debit_negative_for_a_credit_spread():
    o = make_order(long_ask=9.50, short_bid=12.00)
    assert net_debit(o) == pytest.approx(-2.50)


def test_worst_case_loss_debit_spread_is_the_debit():
    # 2.50 debit x 100 x 1 contract
    assert worst_case_loss(make_order()) == pytest.approx(250.0)


def test_worst_case_loss_credit_spread_is_width_minus_credit():
    # 5 wide, 2.50 credit -> 2.50 at risk x 100
    o = make_order(long_ask=9.50, short_bid=12.00)
    assert worst_case_loss(o) == pytest.approx(250.0)


def test_worst_case_loss_scales_with_quantity():
    assert worst_case_loss(make_order(qty=4)) == pytest.approx(1000.0)


def test_quote_sanity_rejects_a_debit_wider_than_the_spread():
    # paying 7.00 for a 5-wide spread is impossible; a stale quote, not an edge
    o = make_order(long_ask=17.00, short_bid=10.00)
    assert any("implausible" in r for r in quote_is_sane(o))


def test_quote_sanity_rejects_nonpositive_quotes():
    assert any("quote" in r for r in quote_is_sane(make_order(long_ask=0.0)))
    assert any("quote" in r for r in quote_is_sane(make_order(short_bid=-1.0)))


def test_quote_sanity_allows_a_normal_spread():
    assert quote_is_sane(make_order()) == ()


def test_loss_gate_allows_at_the_limit():
    # 1500 cap; 3.00 debit x 100 x 5 = 1500 exactly
    o = make_order(long_ask=12.50, short_bid=9.50, qty=5)
    assert worst_case_loss(o) == pytest.approx(1500.0)
    assert check_loss(o, make_snapshot(), Limits()) == ()


def test_loss_gate_vetoes_one_cent_over_the_limit():
    o = make_order(long_ask=12.51, short_bid=9.50, qty=5)
    reasons = check_loss(o, make_snapshot(), Limits())
    assert any("per-position" in r for r in reasons)


def test_aggregate_gate_allows_at_the_limit():
    # 13,750 already open + 1,250 proposed = 15,000 exactly
    existing = (
        OpenPosition(
            key="x",
            opened_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
            worst_case_loss=13750.0,
        ),
    )
    o = make_order(qty=5)  # 2.50 x 100 x 5 = 1250
    assert check_loss(o, make_snapshot(open_positions=existing), Limits()) == ()


def test_aggregate_gate_vetoes_one_dollar_over():
    existing = (
        OpenPosition(
            key="x",
            opened_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
            worst_case_loss=13751.0,
        ),
    )
    o = make_order(qty=5)
    reasons = check_loss(o, make_snapshot(open_positions=existing), Limits())
    assert any("aggregate" in r for r in reasons)
