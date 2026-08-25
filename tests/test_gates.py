import datetime as dt

import pytest

from agent_pkg.gates import (
    Limits,
    OpenPosition,
    Snapshot,
    VerticalOrder,
    check,
    check_greeks,
    check_loss,
    check_structure,
    net_debit,
    net_delta,
    net_delta_notional,
    position_key,
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
        "long_delta": 0.55,
        "short_delta": 0.45,
        "short_iv": 0.18,
        "underlying_price": 765.0,
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


def test_position_key_is_stable_and_distinguishing():
    assert position_key(make_order()) == position_key(make_order(qty=3))
    assert position_key(make_order()) != position_key(make_order(short_strike=770.0))


def test_check_allows_a_clean_order():
    verdict = check(make_order(), make_snapshot(), Limits())
    assert verdict.allowed
    assert verdict.reasons == ()


def test_check_vetoes_when_kill_switch_is_present():
    verdict = check(make_order(), make_snapshot(kill_switch=True), Limits())
    assert not verdict.allowed
    assert any("kill switch" in r for r in verdict.reasons)


def test_check_vetoes_outside_market_hours():
    verdict = check(make_order(), make_snapshot(market_open=False), Limits())
    assert any("market is closed" in r for r in verdict.reasons)


def test_check_vetoes_a_non_paper_account():
    assert any(
        "paper" in r
        for r in check(make_order(), make_snapshot(paper=False), Limits()).reasons
    )
    assert any(
        "prefix" in r
        for r in check(make_order(), make_snapshot(key_prefix="AK"), Limits()).reasons
    )


def test_check_vetoes_an_underlying_off_the_allowlist():
    o = make_order(
        underlying="TSLA",
        long_symbol="TSLA260918C00760000",
        short_symbol="TSLA260918C00765000",
    )
    assert any("allowlist" in r for r in check(o, make_snapshot(), Limits()).reasons)


def test_check_vetoes_too_many_contracts():
    # qty 6 exceeds max_contracts 5; use a cheap spread so loss is not the veto
    o = make_order(long_ask=10.00, short_bid=9.90, qty=6)
    assert any("contracts" in r for r in check(o, make_snapshot(), Limits()).reasons)


def test_check_allows_exactly_max_contracts():
    o = make_order(long_ask=10.00, short_bid=9.90, qty=5)
    assert check(o, make_snapshot(), Limits()).allowed


def test_check_vetoes_a_non_third_friday_expiry():
    o = make_order(expiry=dt.date(2026, 9, 11))  # a weekly, not the monthly
    assert any("third Friday" in r for r in check(o, make_snapshot(), Limits()).reasons)


def test_check_vetoes_an_expiry_that_is_too_near():
    # 2026-09-18 is a third Friday, but only 3 days from this snapshot
    snap = make_snapshot(now=dt.datetime(2026, 9, 15, 15, 0, tzinfo=dt.UTC))
    assert any(
        "days to expiry" in r for r in check(make_order(), snap, Limits()).reasons
    )


def test_check_allows_exactly_min_days_to_expiry():
    snap = make_snapshot(now=dt.datetime(2026, 9, 8, 15, 0, tzinfo=dt.UTC))
    assert check(make_order(), snap, Limits()).allowed


def test_check_vetoes_a_duplicate_inside_the_dedupe_window():
    now = dt.datetime(2026, 9, 1, 15, 0, tzinfo=dt.UTC)
    dup = OpenPosition(
        key=position_key(make_order()),
        opened_at=now - dt.timedelta(minutes=29),
        worst_case_loss=250.0,
    )
    snap = make_snapshot(now=now, open_positions=(dup,))
    assert any("dedupe" in r for r in check(make_order(), snap, Limits()).reasons)


def test_check_allows_a_duplicate_outside_the_dedupe_window():
    now = dt.datetime(2026, 9, 1, 15, 0, tzinfo=dt.UTC)
    old = OpenPosition(
        key=position_key(make_order()),
        opened_at=now - dt.timedelta(minutes=31),
        worst_case_loss=250.0,
    )
    snap = make_snapshot(now=now, open_positions=(old,))
    assert check(make_order(), snap, Limits()).allowed


def test_check_reports_every_problem_at_once():
    o = make_order(
        underlying="TSLA",
        long_symbol="TSLA260918C00760000",
        short_symbol="TSLA260918C00765000",
        qty=99,
    )
    verdict = check(o, make_snapshot(kill_switch=True), Limits())
    assert not verdict.allowed
    assert len(verdict.reasons) >= 3


# --- greeks -----------------------------------------------------------------


def test_net_delta_is_long_minus_short_for_a_call_spread():
    # bull call: long 0.55, short 0.45 -> +0.10 per spread, bullish
    assert net_delta(make_order()) == pytest.approx(0.10)


def test_net_delta_is_positive_for_a_bull_put_spread():
    # short the 765 put (-0.45), long the 760 put (-0.35) -> +0.10, bullish
    o = make_order(option_type="put", long_delta=-0.35, short_delta=-0.45)
    assert net_delta(o) == pytest.approx(0.10)


def test_net_delta_is_negative_for_a_bear_call_spread():
    # short the lower strike (0.55), long the higher (0.45) -> -0.10, bearish
    o = make_order(long_delta=0.45, short_delta=0.55)
    assert net_delta(o) == pytest.approx(-0.10)


def test_net_delta_notional_scales_with_qty_and_price():
    # 0.10 delta x 100 x 3 spreads x $765 = $22,950
    assert net_delta_notional(make_order(qty=3)) == pytest.approx(22950.0)


def test_greeks_reject_a_call_with_negative_delta():
    assert any(
        "sign" in r for r in check_greeks(make_order(short_delta=-0.45), Limits())
    )


def test_greeks_reject_a_put_with_positive_delta():
    o = make_order(option_type="put", long_delta=0.35, short_delta=-0.45)
    assert any("sign" in r for r in check_greeks(o, Limits()))


def test_greeks_reject_an_impossible_delta():
    assert any("range" in r for r in check_greeks(make_order(long_delta=1.4), Limits()))


def test_short_delta_cap_allows_exactly_at_the_limit():
    assert check_greeks(make_order(short_delta=0.50), Limits()) == ()


def test_short_delta_cap_vetoes_one_hundredth_over():
    reasons = check_greeks(make_order(short_delta=0.51), Limits())
    assert any("short leg delta" in r for r in reasons)


def test_short_delta_cap_uses_absolute_value_for_puts():
    o = make_order(option_type="put", long_delta=-0.40, short_delta=-0.51)
    assert any("short leg delta" in r for r in check_greeks(o, Limits()))


def test_aggregate_net_delta_vetoes_a_one_way_book():
    # six existing positions at $7,650 each = $45,900; a seventh takes it over $50,000
    existing = tuple(
        OpenPosition(
            key=f"k{i}",
            opened_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
            worst_case_loss=100.0,
            net_delta_notional=7650.0,
        )
        for i in range(6)
    )
    reasons = check(
        make_order(), make_snapshot(open_positions=existing), Limits()
    ).reasons
    assert any("net delta" in r for r in reasons)


def test_aggregate_net_delta_allows_offsetting_positions():
    """A bearish book plus a bullish order nets down, and the gate must see that
    rather than summing absolute exposures."""
    existing = tuple(
        OpenPosition(
            key=f"k{i}",
            opened_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
            worst_case_loss=100.0,
            net_delta_notional=-7650.0,
        )
        for i in range(6)
    )
    verdict = check(make_order(), make_snapshot(open_positions=existing), Limits())
    assert verdict.allowed, verdict.reasons
