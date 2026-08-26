import datetime as dt

import pytest

from agent_pkg.gates import Limits, Snapshot, VerticalOrder, check
from agent_pkg.positions import Leg, parse_occ, reconstruct

NOW = dt.datetime(2026, 8, 26, 14, 0, tzinfo=dt.UTC)

# The real book on the dev account after the first session that traded: a
# QQQ Sep-18 745/750 call credit spread, three lots. Entry prices, deltas and
# the underlying price are all as Alpaca reported them on 2026-08-26, so the
# expected numbers below are anchored to a fill that actually happened rather
# than to a fixture someone invented.
SHORT_745 = Leg("QQQ260918C00745000", -3, 2.62, 0.1463, 710.73)
LONG_750 = Leg("QQQ260918C00750000", 3, 1.93, 0.1089, 710.73)


def test_parse_occ():
    assert parse_occ("QQQ260918C00745000") == (
        "QQQ",
        dt.date(2026, 9, 18),
        "call",
        745.0,
    )
    assert parse_occ("SPY261218P00612500") == (
        "SPY",
        dt.date(2026, 12, 18),
        "put",
        612.5,
    )


def test_parse_occ_rejects_non_option():
    with pytest.raises(ValueError):
        parse_occ("QQQ")


def test_reconstructs_the_live_spread():
    (pos,) = reconstruct([SHORT_745, LONG_750], NOW)

    # Must match position_key's format exactly or dedupe silently never fires.
    assert pos.key == "QQQ:20260918:call:745-750"
    # Credit of 1.93 - 2.62 = -0.69 on a 5-wide spread, so 4.31 at risk.
    assert pos.worst_case_loss == pytest.approx(1293.0)
    # Short call spread: negative delta.
    assert pos.net_delta_notional == pytest.approx(-7974.39, abs=0.01)
    assert pos.opened_at == NOW


def test_leg_order_does_not_matter():
    a = reconstruct([SHORT_745, LONG_750], NOW)
    b = reconstruct([LONG_750, SHORT_745], NOW)
    assert a == b


def test_empty_book():
    assert reconstruct([], NOW) == ()


def test_key_matches_what_the_dedupe_gate_will_compute():
    """The loaded key and the gate's key must agree, or dedupe is decorative."""
    from agent_pkg.gates import position_key

    order = VerticalOrder(
        underlying="QQQ",
        expiry=dt.date(2026, 9, 18),
        option_type="call",
        long_symbol="QQQ260918C00750000",
        short_symbol="QQQ260918C00745000",
        long_strike=750.0,
        short_strike=745.0,
        long_ask=1.93,
        short_bid=2.62,
        qty=3,
        long_delta=0.1089,
        short_delta=0.1463,
        short_iv=0.17,
        underlying_price=710.73,
    )
    (pos,) = reconstruct([SHORT_745, LONG_750], NOW)
    assert pos.key == position_key(order)


def test_lone_long_leg_risks_only_its_premium():
    (pos,) = reconstruct([LONG_750], NOW)
    assert pos.worst_case_loss == pytest.approx(579.0)  # 1.93 * 100 * 3
    assert pos.net_delta_notional == pytest.approx(0.1089 * 100 * 3 * 710.73)


def test_uncovered_short_refuses_rather_than_guessing():
    """Level 3 cannot hold one, so seeing one means the book is unmodelled."""
    with pytest.raises(RuntimeError, match="uncovered short"):
        reconstruct([SHORT_745], NOW)


def test_partial_close_leaves_a_paired_spread_and_a_leftover():
    """Two lots still form a spread; the third long leg stands alone."""
    positions = reconstruct(
        [Leg("QQQ260918C00745000", -2, 2.62, 0.1463, 710.73), LONG_750], NOW
    )
    assert len(positions) == 2
    spread, leftover = positions
    assert spread.key == "QQQ:20260918:call:745-750"
    assert spread.worst_case_loss == pytest.approx(862.0)  # 4.31 * 100 * 2
    assert leftover.worst_case_loss == pytest.approx(193.0)  # 1.93 * 100 * 1


def test_separate_expiries_do_not_pair():
    other = Leg("QQQ261218C00750000", 3, 4.00, 0.30, 710.73)
    positions = reconstruct([SHORT_745, LONG_750, other], NOW)
    assert len(positions) == 2
    assert {p.key for p in positions} == {
        "QQQ:20260918:call:745-750",
        "QQQ:20261218:call:QQQ261218C00750000",
    }


def make_snapshot(open_positions):
    return Snapshot(
        now=NOW,
        market_open=True,
        kill_switch=False,
        paper=True,
        key_prefix="PK",
        open_positions=open_positions,
    )


def order_for_gate(**over):
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
        "long_delta": 0.45,
        "short_delta": 0.35,
        "short_iv": 0.18,
        "underlying_price": 765.0,
    }
    base.update(over)
    return VerticalOrder(**base)


def test_the_bug_this_module_exists_to_fix():
    """A loaded book must be able to trip the aggregate loss gate.

    Before positions were loaded from the broker, `open_positions` was empty
    at session start, so this order passed no matter what the account held.
    """
    # The order alone risks $250; the held spread another $1,293.
    limits = Limits(max_aggregate_loss=1400.0)
    order = order_for_gate()

    assert check(order, make_snapshot(()), limits).allowed

    held = reconstruct([SHORT_745, LONG_750], NOW)  # $1,293 already at risk
    verdict = check(order, make_snapshot(held), limits)
    assert not verdict.allowed
    assert any("aggregate worst-case loss" in r for r in verdict.reasons)


def test_a_loaded_position_blocks_reopening_the_same_spread():
    """Dedupe across sessions, not just within one."""
    limits = Limits()
    held = reconstruct([SHORT_745, LONG_750], NOW)
    same = order_for_gate(
        underlying="QQQ",
        long_symbol="QQQ260918C00750000",
        short_symbol="QQQ260918C00745000",
        long_strike=750.0,
        short_strike=745.0,
        long_ask=1.93,
        short_bid=2.62,
        qty=3,
        underlying_price=710.73,
    )
    verdict = check(same, make_snapshot(held), limits)
    assert not verdict.allowed
    assert any("dedupe" in r for r in verdict.reasons)


def test_loaded_delta_counts_toward_the_book_delta_gate():
    limits = Limits(max_net_delta_notional=8000.0)
    held = reconstruct([SHORT_745, LONG_750], NOW)  # -$7,974 of delta
    # A small short-delta order on its own is fine.
    order = order_for_gate(long_delta=0.30, short_delta=0.35)
    assert check(order, make_snapshot(()), limits).allowed
    verdict = check(order, make_snapshot(held), limits)
    assert not verdict.allowed
    assert any("book net delta" in r for r in verdict.reasons)
