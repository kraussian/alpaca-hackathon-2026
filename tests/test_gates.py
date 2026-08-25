import datetime as dt

from agent_pkg.gates import (
    Limits,
    VerticalOrder,
    check_structure,
    third_friday,
    width,
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
