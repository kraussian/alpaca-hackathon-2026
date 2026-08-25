# Options Alpha Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a supervised-autonomy options trading agent where an LLM picks defined-risk verticals, a deterministic gate layer can veto every order before it reaches Alpaca, and a public dashboard replays the audit log.

**Architecture:** `gates.py` is pure (no I/O, no network, no model) and holds every risk rule. `broker.py` is the only file that can write to Alpaca and calls gates first. The model reads market data through Alpaca's MCP server, filtered to an explicit read-only allowlist, and writes only through our own tools. Everything the agent does is appended to a JSONL audit log that a Streamlit app renders.

**Tech Stack:** Python 3.12, uv, `alpaca-py`, `anthropic[mcp]`, `mcp`, `streamlit`, `pytest`, `ruff`. Claude Opus 5 (`claude-opus-5`).

**Spec:** `docs/superpowers/specs/2026-08-25-options-alpha-agent-design.md`

## Global Constraints

- Python 3.12+, dependencies managed with `uv` only. Never invoke `pip`.
- Paper trading only. Live keys never enter this repository.
- **Two accounts.** All development trading (Task 1s probe, Task 8s smoke test and supervised sessions) runs on a throwaway dev paper account. The competition account funded to exactly $100,000 is not traded before 28 Aug 2026 15:00 UTC, because the rules require that starting balance and judges pull its activity to score P&L. `ALPACA_ACCOUNT_ROLE` must be `dev` or `competition`; unset is an error, not a default.
- `.env` is gitignored and holds `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER_TRADE=true`. `ANTHROPIC_API_KEY` also comes from the environment.
- Nothing scheduled. No cron, no timer, no loop that survives the session.
- Model ID is exactly `claude-opus-5`. Never append a date suffix. Do not pass `budget_tokens`, `temperature`, `top_p`, or `top_k` on this model; all four return HTTP 400.
- Never touch `C:\projects\alpaca-trader`.
- Run `uv run ruff check .` and `uv run ruff format .` before every commit. Fix all findings.
- Run tests sequentially: `uv run pytest -x -q`.
- Commit messages: imperative subject, capitalized, no trailing period, at most 72 characters, then a blank line, then a body explaining why. No `Co-Authored-By` or generated-with trailers. No em-dashes.

---

### Task 1: Verify Alpaca paper fills a market multi-leg order

**This task gates every other task.** The design assumes market multi-leg orders fill on paper. That is extrapolated from a July single-leg finding on a different account. If it is wrong, the structure decision reopens and the spec is wrong. Do not start Task 2 until this passes.

Must run during regular US market hours. Check `uv run python probe_fills.py` first; it prints whether the market is open.

**Files:**
- Modify: `probe_fills.py`

**Interfaces:**
- Consumes: `third_friday(year, month) -> datetime.date` and `next_monthly(today, min_days) -> datetime.date`, already in `probe_fills.py`.
- Produces: a printed verdict only. No importable API. This file is throwaway and is deleted in Task 10.

- [ ] **Step 1: Add the multi-leg probe function**

Add to `probe_fills.py`, after `poll_status`:

```python
def probe_mleg(tc, key, sec, contracts, exp, spot, wait):
    """Submit one market vertical and report whether paper fills it.

    Buys the strike nearest spot, sells 5 points above it. One contract.
    """
    from alpaca.trading.enums import OrderClass, OrderType, PositionIntent
    from alpaca.trading.requests import MarketOrderRequest, OptionLegRequest

    long_c = min(contracts, key=lambda k: abs(k.strike_price - spot))
    higher = [c for c in contracts if c.strike_price > long_c.strike_price]
    assert higher, "no higher strike available for the short leg"
    short_c = min(higher, key=lambda k: abs(k.strike_price - (long_c.strike_price + 5)))

    print(f"long  {long_c.symbol} strike {long_c.strike_price}")
    print(f"short {short_c.symbol} strike {short_c.strike_price}")

    order = tc.submit_order(
        MarketOrderRequest(
            qty=1,
            order_class=OrderClass.MLEG,
            time_in_force=TimeInForce.DAY,
            legs=[
                OptionLegRequest(
                    symbol=long_c.symbol,
                    ratio_qty=1,
                    side=OrderSide.BUY,
                    position_intent=PositionIntent.BUY_TO_OPEN,
                ),
                OptionLegRequest(
                    symbol=short_c.symbol,
                    ratio_qty=1,
                    side=OrderSide.SELL,
                    position_intent=PositionIntent.SELL_TO_OPEN,
                ),
            ],
        )
    )
    status, px = poll_status(tc, order.id, wait)
    print(f"market MLEG -> {status}  filled_avg_price {px}")
    return status
```

- [ ] **Step 2: Call it from main**

In `probe_fills.py`, immediately before the final `print(f"\nVERDICT: ...")` line, insert:

```python
    print("\n--- MARKET vertical (multi-leg) ---")
    mleg_status = probe_mleg(tc, key, sec, contracts, exp, spot, args.wait)
```

Then replace the existing verdict block with:

```python
    holds = status == "filled" and lstatus != "filled"
    print(
        f"\nVERDICT single-leg: market={status}, marketable-limit={lstatus}. "
        f"Handoff claim {'HOLDS' if holds else 'DOES NOT HOLD'}."
    )
    print(
        f"VERDICT multi-leg: market MLEG={mleg_status}. "
        f"Spec section 11 keystone {'HOLDS' if mleg_status == 'filled' else 'FAILS'}."
    )
```

- [ ] **Step 3: Dry run to confirm nothing is broken**

Run: `uv run python probe_fills.py`
Expected: prints market status, spot, selected contract, quote, then `DRY RUN.` and exits without submitting.

- [ ] **Step 4: Run for real, during market hours**

Run: `uv run python probe_fills.py --trade`
Expected: three orders submitted. Record the printed verdicts.

- [ ] **Step 5: Act on the result**

If `market MLEG=filled`, the spec holds. Proceed to Task 2.

If it did not fill, **stop and report to the operator before writing any other code.** The fallbacks in spec section 11, in order, are: marketable limit multi-leg, then sequential single legs with a gate bounding the unhedged window. Choosing between them changes `gates.py` and `broker.py`, so it is the operator's decision, not the implementer's.

- [ ] **Step 6: Flatten whatever the probe opened**

The probe leaves real paper positions. Close them so they do not pollute the judged P&L:

```bash
uv run python -c "
import os
from alpaca.trading.client import TradingClient
from dotenv import load_dotenv
load_dotenv('.env')
tc = TradingClient(os.environ['ALPACA_API_KEY'], os.environ['ALPACA_SECRET_KEY'], paper=True)
for p in tc.get_all_positions():
    print('closing', p.symbol, p.qty)
    tc.close_position(p.symbol)
"
```

- [ ] **Step 7: Commit**

```bash
git add probe_fills.py
git commit -m "Probe whether paper fills market multi-leg orders

The design rests on this and it was extrapolated from a July single-leg
result on a different account. Recording the answer here so the next
reader does not have to re-run it during market hours to find out."
```

---

### Task 2: Gate types, limits, and the structure gate

**Files:**
- Create: `agent_pkg/__init__.py`
- Create: `agent_pkg/gates.py`
- Create: `tests/test_gates.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Limits(max_contracts: int = 5, max_loss_per_position: float = 1500.0, max_aggregate_loss: float = 15000.0, min_days_to_expiry: int = 10, dedupe_minutes: int = 30, allowed_underlyings: frozenset[str] = frozenset({"SPY","QQQ","IWM"}))`
  - `VerticalOrder(underlying: str, expiry: date, option_type: str, long_symbol: str, short_symbol: str, long_strike: float, short_strike: float, long_ask: float, short_bid: float, qty: int)`
  - `OpenPosition(key: str, opened_at: datetime, worst_case_loss: float)`
  - `Snapshot(now: datetime, market_open: bool, kill_switch: bool, paper: bool, key_prefix: str, open_positions: tuple[OpenPosition, ...])`
  - `Verdict(allowed: bool, reasons: tuple[str, ...])`
  - `third_friday(year: int, month: int) -> date`
  - `width(order: VerticalOrder) -> float`
  - `check_structure(order: VerticalOrder) -> tuple[str, ...]` returning veto reasons, empty when fine

- [ ] **Step 1: Add pytest as a dev dependency**

Run: `uv add --dev pytest`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_gates.py`:

```python
import datetime as dt

import pytest

from agent_pkg.gates import (
    Limits,
    VerticalOrder,
    check_structure,
    third_friday,
    width,
)


def make_order(**over):
    base = dict(
        underlying="SPY",
        expiry=dt.date(2026, 9, 18),
        option_type="call",
        long_symbol="SPY260918C00760000",
        short_symbol="SPY260918C00765000",
        long_strike=760.0,
        short_strike=765.0,
        long_ask=12.00,
        short_bid=9.50,
        qty=1,
    )
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_gates.py -x -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'agent_pkg'`

- [ ] **Step 4: Write the implementation**

Create `agent_pkg/__init__.py` as an empty file.

Create `agent_pkg/gates.py`:

```python
"""Deterministic risk gates.

Pure by design: no network, no account object, no model. Everything this
module needs arrives as an argument, which is what makes the safety-critical
logic the easiest thing in the repository to test.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

OPTION_TYPES = ("call", "put")


@dataclass(frozen=True)
class Limits:
    """Risk limits. Derived in spec section 5, not tuned against returns."""

    max_contracts: int = 5
    max_loss_per_position: float = 1500.0
    max_aggregate_loss: float = 15000.0
    min_days_to_expiry: int = 10
    dedupe_minutes: int = 30
    allowed_underlyings: frozenset[str] = field(
        default_factory=lambda: frozenset({"SPY", "QQQ", "IWM"})
    )


@dataclass(frozen=True)
class VerticalOrder:
    """A two-leg vertical. Quotes are the worst side we could be filled at."""

    underlying: str
    expiry: dt.date
    option_type: str
    long_symbol: str
    short_symbol: str
    long_strike: float
    short_strike: float
    long_ask: float
    short_bid: float
    qty: int


@dataclass(frozen=True)
class OpenPosition:
    key: str
    opened_at: dt.datetime
    worst_case_loss: float


@dataclass(frozen=True)
class Snapshot:
    now: dt.datetime
    market_open: bool
    kill_switch: bool
    paper: bool
    key_prefix: str
    open_positions: tuple[OpenPosition, ...]


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reasons: tuple[str, ...]


def third_friday(year: int, month: int) -> dt.date:
    """Monthly expiry. Naive nearest-expiry logic picks dailies instead."""
    d = dt.date(year, month, 1)
    first_friday = d + dt.timedelta(days=(4 - d.weekday()) % 7)
    return first_friday + dt.timedelta(days=14)


def width(order: VerticalOrder) -> float:
    return abs(order.long_strike - order.short_strike)


def check_structure(order: VerticalOrder) -> tuple[str, ...]:
    """Reject anything that is not a well-formed two-leg vertical."""
    reasons: list[str] = []
    if order.option_type not in OPTION_TYPES:
        reasons.append(
            f"option_type {order.option_type!r} is not one of {OPTION_TYPES}"
        )
    if order.long_strike == order.short_strike:
        reasons.append("both legs use the same strike, so this is not a vertical")
    if order.qty <= 0:
        reasons.append(f"qty {order.qty} must be positive")
    if not order.long_symbol.startswith(order.underlying):
        reasons.append(
            f"long leg {order.long_symbol} is not on underlying {order.underlying}"
        )
    if not order.short_symbol.startswith(order.underlying):
        reasons.append(
            f"short leg {order.short_symbol} is not on underlying {order.underlying}"
        )
    if order.long_symbol == order.short_symbol:
        reasons.append("both legs are the same contract")
    return tuple(reasons)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_gates.py -x -q`
Expected: PASS, 7 passed

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add agent_pkg/ tests/ pyproject.toml uv.lock
git commit -m "Add gate types and the structure gate

gates.py is kept pure so the safety-critical logic can be tested without
a network, an account, or a model. Every other module in this build has
an external dependency; this one deliberately does not, and that is the
reason the risk rules live here rather than inside broker.py."
```

---

### Task 3: Loss arithmetic and the loss gates

**Files:**
- Modify: `agent_pkg/gates.py`
- Modify: `tests/test_gates.py`

**Interfaces:**
- Consumes: `VerticalOrder`, `Limits`, `OpenPosition`, `width` from Task 2.
- Produces:
  - `net_debit(order: VerticalOrder) -> float` (per share, positive means debit)
  - `quote_is_sane(order: VerticalOrder) -> tuple[str, ...]`
  - `worst_case_loss(order: VerticalOrder) -> float` (dollars, whole position)
  - `check_loss(order: VerticalOrder, snapshot: Snapshot, limits: Limits) -> tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gates.py`:

```python
from agent_pkg.gates import (
    OpenPosition,
    Snapshot,
    check_loss,
    net_debit,
    quote_is_sane,
    worst_case_loss,
)


def make_snapshot(**over):
    base = dict(
        now=dt.datetime(2026, 9, 1, 15, 0, tzinfo=dt.UTC),
        market_open=True,
        kill_switch=False,
        paper=True,
        key_prefix="PK",
        open_positions=(),
    )
    base.update(over)
    return Snapshot(**base)


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gates.py -x -q`
Expected: FAIL, `ImportError: cannot import name 'net_debit'`

- [ ] **Step 3: Write the implementation**

Append to `agent_pkg/gates.py`:

```python
def net_debit(order: VerticalOrder) -> float:
    """Per-share cost at the worst fill: pay the ask, receive the bid.

    Positive means a debit spread, negative means a credit spread. Using the
    worst side of the quote rather than the mid means the loss gate cannot be
    defeated by the spread widening between the check and the fill.
    """
    return order.long_ask - order.short_bid


def quote_is_sane(order: VerticalOrder) -> tuple[str, ...]:
    """Reject quotes that imply an impossible spread price.

    A stale or crossed quote produces a loss figure the gates would then
    trust. Catching it here means worst_case_loss is only ever asked about
    numbers that could actually occur.
    """
    reasons: list[str] = []
    if order.long_ask <= 0:
        reasons.append(f"long leg quote {order.long_ask} is not a positive price")
    if order.short_bid <= 0:
        reasons.append(f"short leg quote {order.short_bid} is not a positive price")
    w = width(order)
    if w <= 0:
        reasons.append("spread width is zero")
    elif abs(net_debit(order)) >= w:
        reasons.append(
            f"implausible quote: net {net_debit(order):.2f} is not inside the "
            f"{w:.2f} wide spread"
        )
    return tuple(reasons)


def worst_case_loss(order: VerticalOrder) -> float:
    """Maximum dollars this position can lose, assuming the worst fill.

    Only meaningful when quote_is_sane(order) is empty.
    """
    d = net_debit(order)
    per_share = d if d > 0 else width(order) + d
    return per_share * 100 * order.qty


def check_loss(
    order: VerticalOrder, snapshot: Snapshot, limits: Limits
) -> tuple[str, ...]:
    """Backstop, not a shaper. Silence here is the intended behaviour."""
    reasons = list(quote_is_sane(order))
    if reasons:
        return tuple(reasons)

    loss = worst_case_loss(order)
    if loss > limits.max_loss_per_position:
        reasons.append(
            f"per-position worst-case loss ${loss:,.2f} exceeds "
            f"${limits.max_loss_per_position:,.2f}"
        )

    open_loss = sum(p.worst_case_loss for p in snapshot.open_positions)
    if open_loss + loss > limits.max_aggregate_loss:
        reasons.append(
            f"aggregate worst-case loss ${open_loss + loss:,.2f} exceeds "
            f"${limits.max_aggregate_loss:,.2f} "
            f"(${open_loss:,.2f} already open)"
        )
    return tuple(reasons)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gates.py -x -q`
Expected: PASS, 19 passed

- [ ] **Step 5: Mutation-check the boundary tests**

Temporarily change `if loss > limits.max_loss_per_position:` to `if loss > limits.max_loss_per_position + 100:` and run the tests.
Expected: `test_loss_gate_vetoes_one_cent_over_the_limit` FAILS.
Revert the change and confirm the suite passes again. A boundary test that survives this is not testing the boundary.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add agent_pkg/gates.py tests/test_gates.py
git commit -m "Add worst-case loss arithmetic and the loss gates

Loss is computed from the worst side of the quote, paying the ask and
receiving the bid, so a spread that widens between the check and the fill
cannot walk a position past its limit.

quote_is_sane runs first and short-circuits. Without it a stale or crossed
quote yields a loss figure the gates would go on to trust, which is worse
than no gate because it looks like it worked."
```

---

### Task 4: Categorical gates and the aggregator

**Files:**
- Modify: `agent_pkg/gates.py`
- Modify: `tests/test_gates.py`

**Interfaces:**
- Consumes: everything from Tasks 2 and 3.
- Produces:
  - `position_key(order: VerticalOrder) -> str`
  - `check(order: VerticalOrder, snapshot: Snapshot, limits: Limits) -> Verdict`

`check` collects reasons from every gate rather than short-circuiting, so the model sees all its problems at once instead of fixing them one round-trip at a time.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gates.py`:

```python
from agent_pkg.gates import check, position_key


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gates.py -x -q`
Expected: FAIL, `ImportError: cannot import name 'check'`

- [ ] **Step 3: Write the implementation**

Append to `agent_pkg/gates.py`:

```python
def position_key(order: VerticalOrder) -> str:
    """Identity of a spread, ignoring size. Two fills of the same spread at
    different quantities are the same position for dedupe purposes."""
    lo, hi = sorted((order.long_strike, order.short_strike))
    return f"{order.underlying}:{order.expiry:%Y%m%d}:{order.option_type}:{lo:g}-{hi:g}"


def check(order: VerticalOrder, snapshot: Snapshot, limits: Limits) -> Verdict:
    """Run every gate and collect all reasons.

    Deliberately does not short-circuit. The reasons go back to the model,
    and one round-trip per problem wastes a supervised session.
    """
    reasons: list[str] = []

    if snapshot.kill_switch:
        reasons.append("kill switch is engaged")
    if not snapshot.paper:
        reasons.append("client is not in paper mode")
    if snapshot.key_prefix != "PK":
        reasons.append(
            f"API key prefix {snapshot.key_prefix!r} is not a paper key prefix"
        )
    if not snapshot.market_open:
        reasons.append("market is closed")

    reasons.extend(check_structure(order))

    if order.underlying not in limits.allowed_underlyings:
        reasons.append(
            f"{order.underlying} is not on the allowlist "
            f"{sorted(limits.allowed_underlyings)}"
        )
    if order.qty > limits.max_contracts:
        reasons.append(
            f"{order.qty} contracts exceeds the limit of {limits.max_contracts}"
        )

    if order.expiry != third_friday(order.expiry.year, order.expiry.month):
        reasons.append(
            f"expiry {order.expiry} is not the third Friday "
            f"({third_friday(order.expiry.year, order.expiry.month)})"
        )
    days = (order.expiry - snapshot.now.date()).days
    if days < limits.min_days_to_expiry:
        reasons.append(
            f"{days} days to expiry is below the minimum of {limits.min_days_to_expiry}"
        )

    key = position_key(order)
    cutoff = snapshot.now - dt.timedelta(minutes=limits.dedupe_minutes)
    if any(p.key == key and p.opened_at > cutoff for p in snapshot.open_positions):
        reasons.append(
            f"dedupe: {key} was already opened within {limits.dedupe_minutes} minutes"
        )

    reasons.extend(check_loss(order, snapshot, limits))

    return Verdict(allowed=not reasons, reasons=tuple(reasons))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gates.py -x -q`
Expected: PASS, 33 passed

- [ ] **Step 5: Mutation-check the dedupe window**

Temporarily change `p.opened_at > cutoff` to `p.opened_at > cutoff - dt.timedelta(minutes=10)` and run the tests.
Expected: `test_check_allows_a_duplicate_outside_the_dedupe_window` FAILS. Revert.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add agent_pkg/gates.py tests/test_gates.py
git commit -m "Add the categorical gates and the check aggregator

check collects every veto reason instead of returning the first one. The
reasons are fed back to the model, and short-circuiting would cost one
round-trip per problem in a session measured in minutes.

The expiry gate checks both distance and third-Friday alignment. Distance
alone would accept a weekly, which is the footgun that showed up on the
very first chain query against this account."
```

---

### Task 5: Audit log

**Files:**
- Create: `agent_pkg/audit.py`
- Create: `tests/test_audit.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `scrub(text: str) -> str`
  - `AuditLog(session_id: str, directory: Path = Path("logs"))` with `.write(event: str, **fields) -> dict` and `.path -> Path`

- [ ] **Step 1: Narrow the jsonl ignore rule**

In `.gitignore`, replace the line `*.jsonl` with:

```
!logs/*.jsonl
```

Then verify `logs/` audit files are trackable while nothing else changes:

Run: `git check-ignore -v logs/session-test.jsonl || echo "trackable"`
Expected: `trackable`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_audit.py`:

```python
import json

from agent_pkg.audit import AuditLog, scrub


def test_scrub_removes_account_numbers():
    assert "PAEXAMPLE1234" not in scrub("account PAEXAMPLE1234 is active")
    assert "<account>" in scrub("account PAEXAMPLE1234 is active")


def test_scrub_removes_api_keys():
    out = scrub("key PKTESTKEY0123456789AB here")
    assert "PKTESTKEY0123456789AB" not in out
    assert "<key>" in out


def test_scrub_leaves_ordinary_text_alone():
    assert (
        scrub("bought SPY260918C00760000 at 12.00")
        == "bought SPY260918C00760000 at 12.00"
    )


def test_write_appends_one_json_object_per_call(tmp_path):
    log = AuditLog(session_id="test", directory=tmp_path)
    log.write("decision", reasoning="looks cheap")
    log.write("gate_verdict", allowed=False, reasons=["kill switch is engaged"])

    lines = log.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event"] == "decision"
    assert first["session_id"] == "test"
    assert first["reasoning"] == "looks cheap"
    assert "timestamp" in first


def test_write_scrubs_nested_values(tmp_path):
    log = AuditLog(session_id="test", directory=tmp_path)
    log.write("submission", detail={"account": "PAEXAMPLE1234"})
    written = log.path.read_text(encoding="utf-8")
    assert "PAEXAMPLE1234" not in written
    assert "<account>" in written
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit.py -x -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'agent_pkg.audit'`

- [ ] **Step 4: Write the implementation**

Create `agent_pkg/audit.py`:

```python
"""Append-only decision log.

Written before the order is submitted, not after the fill. If the submission
throws, the reasoning that led to it is what you need, and a log written
afterwards would not have it.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

_ACCOUNT = re.compile(r"\bPA[A-Z0-9]{8,}\b")
_KEY = re.compile(r"\bPK[A-Z0-9]{16,}\b")


def scrub(text: str) -> str:
    """Remove account numbers and API keys.

    Runs at write time, not before submission. The submission rules assume
    anything submitted is public, and this log ships in a public repository
    to feed the dashboard.
    """
    return _ACCOUNT.sub("<account>", _KEY.sub("<key>", text))


class AuditLog:
    def __init__(self, session_id: str, directory: Path = Path("logs")) -> None:
        self.session_id = session_id
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / f"session-{session_id}.jsonl"

    def write(self, event: str, **fields: object) -> dict:
        record = {
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            "session_id": self.session_id,
            "event": event,
            **fields,
        }
        line = scrub(json.dumps(record, default=str))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return json.loads(line)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit.py -x -q`
Expected: PASS, 5 passed

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add agent_pkg/audit.py tests/test_audit.py .gitignore
git commit -m "Add the append-only audit log

Records are written before submission rather than after the fill. When a
submission throws, the reasoning that produced it is the thing worth
having, and a log written after the fact would not contain it.

Scrubbing happens at write time because these files ship in a public
repository to feed the dashboard, so there is no later moment at which
scrubbing would still be a choice."
```

---

### Task 6: Broker, the single write path

**Files:**
- Create: `agent_pkg/broker.py`
- Create: `tests/test_broker.py`

**Interfaces:**
- Consumes: `gates.check`, `gates.Limits`, `gates.VerticalOrder`, `gates.Snapshot`, `gates.OpenPosition`, `gates.position_key`, `gates.worst_case_loss`, `audit.AuditLog`.
- Produces:
  - `KILL_FILE: Path` (module constant, `Path(".kill")`)
  - `Broker(limits: Limits, audit: AuditLog, kill_file: Path = KILL_FILE)` with:
    - `.snapshot(open_positions: tuple[OpenPosition, ...]) -> Snapshot`
    - `.open_vertical(order: VerticalOrder) -> dict` returning `{"submitted": bool, "reasons": list[str], "order_id": str | None}`
    - `.close_vertical(long_symbol: str, short_symbol: str) -> dict`

Construction raises `RuntimeError` if the environment is not paper. That check is in `__init__` rather than in the submit path so a misconfigured process cannot get far enough to have an order to submit.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_broker.py`:

```python
import datetime as dt

import pytest

from agent_pkg.audit import AuditLog
from agent_pkg.broker import Broker
from agent_pkg.gates import Limits, VerticalOrder


class FakeTradingClient:
    """Stands in for alpaca-py. Records what would have been submitted."""

    def __init__(self):
        self.submitted = []

    def submit_order(self, request):
        self.submitted.append(request)
        return type("Order", (), {"id": "fake-order-id"})()


def make_order(**over):
    base = dict(
        underlying="SPY",
        expiry=dt.date(2026, 9, 18),
        option_type="call",
        long_symbol="SPY260918C00760000",
        short_symbol="SPY260918C00765000",
        long_strike=760.0,
        short_strike=765.0,
        long_ask=12.00,
        short_bid=9.50,
        qty=1,
    )
    base.update(over)
    return VerticalOrder(**base)


def make_broker(tmp_path, monkeypatch, **over):
    monkeypatch.setenv("ALPACA_PAPER_TRADE", over.pop("paper_env", "true"))
    monkeypatch.setenv("ALPACA_API_KEY", over.pop("key", "PKTESTKEY0123456789AB"))
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    broker = Broker(
        limits=Limits(),
        audit=AuditLog(session_id="test", directory=tmp_path),
        kill_file=tmp_path / ".kill",
        client=FakeTradingClient(),
        clock_is_open=over.pop("clock_is_open", True),
    )
    return broker


def test_broker_refuses_to_construct_when_not_paper(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="paper"):
        make_broker(tmp_path, monkeypatch, paper_env="false")


def test_broker_refuses_a_non_paper_key_prefix(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="prefix"):
        make_broker(tmp_path, monkeypatch, key="AKLIVEKEY0123456789AB")


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_broker.py -x -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'agent_pkg.broker'`

- [ ] **Step 3: Write the implementation**

Create `agent_pkg/broker.py`:

```python
"""The only file in this repository that can write to Alpaca.

Every mutating call routes through here and every one of them runs the gates
first. That is the whole safety argument: it is checkable by grepping for
submit_order, and it holds only as long as this stays the single write path.
"""

from __future__ import annotations

import os
from pathlib import Path

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, PositionIntent, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, OptionLegRequest

from agent_pkg.audit import AuditLog
from agent_pkg.gates import (
    Limits,
    OpenPosition,
    Snapshot,
    VerticalOrder,
    check,
    position_key,
    worst_case_loss,
)

KILL_FILE = Path(".kill")


class Broker:
    def __init__(
        self,
        limits: Limits,
        audit: AuditLog,
        kill_file: Path = KILL_FILE,
        client: object | None = None,
        clock_is_open: bool | None = None,
    ) -> None:
        paper_env = os.environ.get("ALPACA_PAPER_TRADE", "true").lower()
        if paper_env != "true":
            raise RuntimeError(
                f"ALPACA_PAPER_TRADE is {paper_env!r}, refusing: paper only"
            )
        key = os.environ["ALPACA_API_KEY"]
        if not key.startswith("PK"):
            raise RuntimeError(
                f"API key prefix {key[:2]!r} is not a paper prefix, refusing"
            )

        self.limits = limits
        self.audit = audit
        self.kill_file = Path(kill_file)
        self._clock_override = clock_is_open
        self.client = client or TradingClient(
            key, os.environ["ALPACA_SECRET_KEY"], paper=True
        )
        self._open: list[OpenPosition] = []

    def _market_open(self) -> bool:
        if self._clock_override is not None:
            return self._clock_override
        return bool(self.client.get_clock().is_open)

    def snapshot(
        self, open_positions: tuple[OpenPosition, ...] | None = None
    ) -> Snapshot:
        import datetime as dt

        return Snapshot(
            now=dt.datetime.now(dt.UTC),
            market_open=self._market_open(),
            kill_switch=self.kill_file.exists(),
            paper=True,
            key_prefix=os.environ["ALPACA_API_KEY"][:2],
            open_positions=open_positions
            if open_positions is not None
            else tuple(self._open),
        )

    def open_vertical(self, order: VerticalOrder) -> dict:
        snap = self.snapshot()
        verdict = check(order, snap, self.limits)
        self.audit.write(
            "gate_verdict",
            allowed=verdict.allowed,
            reasons=list(verdict.reasons),
            order=vars(order),
        )
        if not verdict.allowed:
            return {
                "submitted": False,
                "reasons": list(verdict.reasons),
                "order_id": None,
            }

        request = MarketOrderRequest(
            qty=order.qty,
            order_class=OrderClass.MLEG,
            time_in_force=TimeInForce.DAY,
            legs=[
                OptionLegRequest(
                    symbol=order.long_symbol,
                    ratio_qty=1,
                    side=OrderSide.BUY,
                    position_intent=PositionIntent.BUY_TO_OPEN,
                ),
                OptionLegRequest(
                    symbol=order.short_symbol,
                    ratio_qty=1,
                    side=OrderSide.SELL,
                    position_intent=PositionIntent.SELL_TO_OPEN,
                ),
            ],
        )
        submitted = self.client.submit_order(request)
        self._open.append(
            OpenPosition(
                key=position_key(order),
                opened_at=snap.now,
                worst_case_loss=worst_case_loss(order),
            )
        )
        self.audit.write("submission", order_id=str(submitted.id), order=vars(order))
        return {"submitted": True, "reasons": [], "order_id": str(submitted.id)}

    def close_position(self, symbol: str) -> dict:
        if self.kill_file.exists():
            self.audit.write(
                "gate_verdict", allowed=False, reasons=["kill switch is engaged"]
            )
            return {
                "submitted": False,
                "reasons": ["kill switch is engaged"],
                "order_id": None,
            }
        self.client.close_position(symbol)
        self.audit.write("submission", action="close", symbol=symbol)
        return {"submitted": True, "reasons": [], "order_id": None}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_broker.py -x -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Verify the single-write-path invariant**

Run: `uv run python -c "import subprocess,sys; out=subprocess.run(['git','grep','-n','submit_order\|close_position\|cancel_order'],capture_output=True,text=True).stdout; bad=[l for l in out.splitlines() if not l.startswith(('agent_pkg/broker.py','tests/','probe_fills.py'))]; print('\n'.join(bad) or 'invariant holds'); sys.exit(1 if bad else 0)"`
Expected: `invariant holds`

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format .
git add agent_pkg/broker.py tests/test_broker.py
git commit -m "Add the broker as the single Alpaca write path

The paper check runs in __init__ rather than in the submit path so a
misconfigured process dies before it has an order to submit, instead of
building one and refusing at the last moment.

Vetoes are written to the audit log before the return, so a blocked order
leaves the same trail as a submitted one. A veto that left no record would
make the gate layer invisible in exactly the runs where it mattered."
```

---

### Task 7: MCP read-only allowlist

**This is the task that decides whether the gate layer means anything.** Alpaca's MCP server exposes 72 tools including `place_option_order`, `place_stock_order`, `place_crypto_order`, `close_all_positions`, `close_position`, `cancel_all_orders`, `cancel_order_by_id`, `replace_order_by_id`, `exercise_options_position` and `update_account_config`. If any of those reach the model, it can place an order without passing a single gate.

The filter is an explicit allowlist, never a denylist. A denylist fails open the day Alpaca adds a tool.

**Files:**
- Create: `agent_pkg/mcp_tools.py`
- Create: `tests/test_mcp_tools.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `READ_ONLY_TOOLS: frozenset[str]`
  - `filter_tools(tools: list) -> list` keeping only objects whose `.name` is in `READ_ONLY_TOOLS`

- [ ] **Step 1: Add the MCP dependencies**

Run: `uv add "anthropic[mcp]" mcp`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_mcp_tools.py`:

```python
from agent_pkg.mcp_tools import READ_ONLY_TOOLS, filter_tools

MUTATING = [
    "place_option_order",
    "place_stock_order",
    "place_crypto_order",
    "close_position",
    "close_all_positions",
    "cancel_order_by_id",
    "cancel_all_orders",
    "replace_order_by_id",
    "exercise_options_position",
    "do_not_exercise_options_position",
    "update_account_config",
    "create_watchlist",
    "delete_watchlist_by_id",
    "add_asset_to_watchlist_by_id",
    "remove_asset_from_watchlist_by_id",
    "update_watchlist_by_id",
    "create_locate",
]


class FakeTool:
    def __init__(self, name):
        self.name = name


def test_no_mutating_tool_is_on_the_allowlist():
    for name in MUTATING:
        assert name not in READ_ONLY_TOOLS, (
            f"{name} would let the model bypass the gates"
        )


def test_filter_drops_every_mutating_tool():
    tools = [FakeTool(n) for n in MUTATING] + [FakeTool("get_account_info")]
    kept = [t.name for t in filter_tools(tools)]
    assert kept == ["get_account_info"]


def test_filter_drops_unknown_tools():
    kept = filter_tools([FakeTool("some_tool_alpaca_added_last_week")])
    assert kept == []


def test_allowlist_covers_what_the_agent_actually_needs():
    for name in (
        "get_account_info",
        "get_all_positions",
        "get_clock",
        "get_option_contracts",
        "get_option_latest_quote",
        "get_stock_latest_trade",
    ):
        assert name in READ_ONLY_TOOLS
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_tools.py -x -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'agent_pkg.mcp_tools'`

- [ ] **Step 4: Write the implementation**

Create `agent_pkg/mcp_tools.py`:

```python
"""Read-only filter over Alpaca's MCP tools.

Alpaca's MCP server exposes order placement, position closing and order
cancellation alongside its market data tools. Handing the model the unfiltered
list would let it place an order without passing a single gate, which would
reduce the entire risk layer to decoration.

This is an allowlist and must stay one. A denylist fails open the day Alpaca
ships a tool nobody here has heard of.
"""

from __future__ import annotations

READ_ONLY_TOOLS = frozenset(
    {
        # account and positions
        "get_account_info",
        "get_all_positions",
        "get_open_position",
        "get_portfolio_history",
        # orders, read side only
        "get_orders",
        "get_order_by_id",
        # market state
        "get_clock",
        "get_calendar",
        # options
        "get_option_contracts",
        "get_option_chain",
        "get_option_snapshot",
        "get_option_latest_quote",
        "get_option_latest_trade",
        "get_option_bars",
        # underlying
        "get_stock_latest_trade",
        "get_stock_latest_quote",
        "get_stock_snapshot",
        "get_stock_bars",
        # context
        "get_news",
    }
)


def filter_tools(tools: list) -> list:
    """Keep only tools on the allowlist. Everything else is dropped silently."""
    return [t for t in tools if t.name in READ_ONLY_TOOLS]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_tools.py -x -q`
Expected: PASS, 4 passed

- [ ] **Step 6: Verify the allowlist against the live server**

Run: `uv run python mcp_smoke.py` and confirm it still reports 72 tools. Then:

```bash
uv run python -c "
from agent_pkg.mcp_tools import READ_ONLY_TOOLS
print(f'allowlist size: {len(READ_ONLY_TOOLS)} of 72 exposed')
"
```
Expected: `allowlist size: 19 of 72 exposed`

- [ ] **Step 7: Commit**

```bash
uv run ruff check . && uv run ruff format .
git add agent_pkg/mcp_tools.py tests/test_mcp_tools.py pyproject.toml uv.lock
git commit -m "Restrict the model to read-only Alpaca MCP tools

Alpaca's MCP server exposes place_option_order, close_all_positions and
cancel_all_orders in the same list as its quote endpoints. Passing that
list to the model unfiltered would give it a write path that never touches
broker.py, and every gate in this repository would become decoration.

The filter is an allowlist rather than a denylist on purpose. A denylist
is correct only until Alpaca ships a tool nobody here has heard of, and it
fails open rather than closed on that day."
```

---

### Task 8: Agent session loop

**Files:**
- Create: `agent_pkg/tools.py`
- Create: `agent_pkg/session.py`
- Create: `agent_pkg/__main__.py`

**Interfaces:**
- Consumes: `Broker`, `AuditLog`, `Limits`, `VerticalOrder`, `filter_tools`.
- Produces: `run_session(minutes: int, max_orders: int, underlyings: list[str]) -> None`, invoked as `uv run python -m agent_pkg --minutes 60 --max-orders 3`.

Model configuration: `claude-opus-5`, thinking is on by default so the `thinking` parameter is omitted, `output_config={"effort": "high"}`. Do not pass `budget_tokens`, `temperature`, `top_p` or `top_k`; all four return HTTP 400 on this model.

- [ ] **Step 1: Write the model-facing tools**

Create `agent_pkg/tools.py`:

```python
"""Write tools exposed to the model. Every one routes through the broker."""

from __future__ import annotations

import datetime as dt

from anthropic import beta_tool

from agent_pkg.gates import VerticalOrder

_BROKER = None
_STATE = {"orders": 0, "max_orders": 0}


def bind(broker, max_orders: int) -> None:
    global _BROKER
    _BROKER = broker
    _STATE["orders"] = 0
    _STATE["max_orders"] = max_orders


@beta_tool
def open_vertical(
    underlying: str,
    expiry: str,
    option_type: str,
    long_symbol: str,
    short_symbol: str,
    long_strike: float,
    short_strike: float,
    long_ask: float,
    short_bid: float,
    qty: int,
) -> str:
    """Open a defined-risk vertical spread. Every order passes the risk gates
    first and may be vetoed; a veto is returned to you with its reasons so you
    can propose something else.

    Args:
        underlying: Underlying ticker, for example SPY.
        expiry: Expiry date as YYYY-MM-DD. Must be a monthly third Friday.
        option_type: Either "call" or "put".
        long_symbol: OCC symbol of the leg you are buying.
        short_symbol: OCC symbol of the leg you are selling.
        long_strike: Strike of the long leg.
        short_strike: Strike of the short leg.
        long_ask: Current ask on the long leg. Used for worst-case risk.
        short_bid: Current bid on the short leg. Used for worst-case risk.
        qty: Number of spreads.
    """
    if _STATE["orders"] >= _STATE["max_orders"]:
        return f"VETO: session order cap of {_STATE['max_orders']} already reached"

    order = VerticalOrder(
        underlying=underlying,
        expiry=dt.date.fromisoformat(expiry),
        option_type=option_type,
        long_symbol=long_symbol,
        short_symbol=short_symbol,
        long_strike=long_strike,
        short_strike=short_strike,
        long_ask=long_ask,
        short_bid=short_bid,
        qty=qty,
    )
    result = _BROKER.open_vertical(order)
    if not result["submitted"]:
        return "VETO: " + "; ".join(result["reasons"])
    _STATE["orders"] += 1
    return f"SUBMITTED order {result['order_id']}"


@beta_tool
def close_position(symbol: str) -> str:
    """Close an open option position.

    Args:
        symbol: The OCC symbol of the position to close.
    """
    result = _BROKER.close_position(symbol)
    return "CLOSED" if result["submitted"] else "VETO: " + "; ".join(result["reasons"])


@beta_tool
def engage_kill_switch(reason: str) -> str:
    """Stop all trading for the rest of this session. Use this if account state
    looks wrong or you are not confident it is safe to continue.

    Args:
        reason: Why you are stopping.
    """
    _BROKER.kill_file.write_text(reason, encoding="utf-8")
    _BROKER.audit.write("kill_switch", reason=reason)
    return f"KILL SWITCH ENGAGED: {reason}"
```

- [ ] **Step 2: Write the session loop**

Create `agent_pkg/session.py`:

```python
"""One bounded, supervised trading session.

Two independent stop conditions, wall clock and order count, because either
alone fails open if the other is misconfigured. Nothing here schedules
anything; when the process exits, the agent is gone.
"""

from __future__ import annotations

import datetime as dt
import os

from anthropic import AsyncAnthropic
from anthropic.lib.tools.mcp import async_mcp_tool
from dotenv import dotenv_values
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from agent_pkg import tools as write_tools
from agent_pkg.audit import AuditLog
from agent_pkg.broker import Broker
from agent_pkg.gates import Limits
from agent_pkg.mcp_tools import filter_tools

MODEL = "claude-opus-5"

SYSTEM = """You are a supervised options trading agent on an Alpaca paper account.

You may only open defined-risk vertical spreads on monthly (third Friday)
expiries. Every order you propose passes a deterministic risk gate layer that
can veto it. A veto is not a failure; it comes back with reasons and you may
propose something else.

Before proposing an order:
1. Read the account and current positions.
2. Read the underlying's price and the option chain for the monthly expiry.
3. Read the actual bid and ask on both legs. Pass the long leg's ask and the
   short leg's bid, not the mid. The gates compute worst-case risk from them.

State your reasoning before each tool call. That reasoning is logged and is
the record of why this position exists.

You are not being scored on how many trades you place. If nothing looks
worth doing, say so and stop.
"""


async def run_session(minutes: int, max_orders: int, underlyings: list[str]) -> None:
    session_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    audit = AuditLog(session_id=session_id)
    limits = Limits(allowed_underlyings=frozenset(underlyings))
    broker = Broker(limits=limits, audit=audit)
    write_tools.bind(broker, max_orders)

    deadline = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=minutes)
    audit.write(
        "session_start",
        minutes=minutes,
        max_orders=max_orders,
        underlyings=underlyings,
        limits=vars(limits)
        | {"allowed_underlyings": sorted(limits.allowed_underlyings)},
    )

    env = {**os.environ, "ALPACA_PAPER_TRADE": "true", **dotenv_values(".env")}
    client = AsyncAnthropic()

    async with stdio_client(
        StdioServerParameters(command="uvx", args=["alpaca-mcp-server"], env=env)
    ) as (read, write):
        async with ClientSession(read, write) as mcp:
            await mcp.initialize()
            listed = (await mcp.list_tools()).tools
            allowed = filter_tools(listed)
            audit.write(
                "mcp_tools",
                exposed=len(listed),
                allowed=[t.name for t in allowed],
            )

            prompt = (
                f"The session ends at {deadline.isoformat()} and you may place at "
                f"most {max_orders} orders. Permitted underlyings: "
                f"{', '.join(underlyings)}. Review the account and decide whether "
                f"any vertical is worth opening today."
            )

            runner = client.beta.messages.tool_runner(
                model=MODEL,
                max_tokens=16000,
                output_config={"effort": "high"},
                system=SYSTEM,
                tools=[async_mcp_tool(t, mcp) for t in allowed]
                + [
                    write_tools.open_vertical,
                    write_tools.close_position,
                    write_tools.engage_kill_switch,
                ],
                messages=[{"role": "user", "content": prompt}],
            )

            async for message in runner:
                for block in message.content:
                    if block.type == "text" and block.text.strip():
                        audit.write("decision", reasoning=block.text)
                        print(block.text)
                    elif block.type == "tool_use":
                        audit.write("tool_call", tool=block.name, input=block.input)
                        print(f"  -> {block.name}({block.input})")
                if dt.datetime.now(dt.UTC) >= deadline:
                    audit.write("session_stop", reason="wall clock deadline reached")
                    print("\nSession deadline reached, stopping.")
                    break

    audit.write("session_end", log=str(audit.path))
    print(f"\nAudit log: {audit.path}")
```

- [ ] **Step 3: Write the entry point**

Create `agent_pkg/__main__.py`:

```python
import argparse
import asyncio

from dotenv import load_dotenv

from agent_pkg.session import run_session


def main() -> None:
    load_dotenv(".env")
    ap = argparse.ArgumentParser(prog="agent_pkg")
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--max-orders", type=int, default=3)
    ap.add_argument("--underlyings", nargs="+", default=["SPY", "QQQ", "IWM"])
    args = ap.parse_args()
    asyncio.run(run_session(args.minutes, args.max_orders, args.underlyings))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Smoke-test with the kill switch pre-engaged**

This proves the gates hold end to end before the agent is ever allowed to trade.

```bash
echo "smoke test" > .kill
uv run python -m agent_pkg --minutes 5 --max-orders 1
```
Expected: the agent reads account and chain data normally, and any `open_vertical` call returns `VETO: kill switch is engaged`. Nothing is submitted. Confirm with `git grep -c gate_verdict logs/*.jsonl`.

- [ ] **Step 5: Remove the kill file and run a real supervised session**

```bash
rm .kill
uv run python -m agent_pkg --minutes 30 --max-orders 1
```
Watch it. Keep a second terminal ready with `echo stop > .kill` as the manual abort.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format .
git add agent_pkg/tools.py agent_pkg/session.py agent_pkg/__main__.py
git commit -m "Add the bounded supervised session loop

Two stop conditions, wall clock and order count, are enforced separately.
Either one alone fails open if the other is misconfigured, and the cost of
the redundancy is four lines.

The session order cap lives in tools.py rather than in the gates because it
is a property of this run, not of the account. gates.py stays pure and
answers the same question the same way regardless of how long the process
has been alive."
```

---

### Task 9: Dashboard

**Files:**
- Create: `app.py`
- Create: `.streamlit/config.toml`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: audit log JSONL files in `logs/`.
- Produces: a Streamlit app. Holds no Alpaca credentials and has no write path.

- [ ] **Step 1: Add streamlit**

Run: `uv add streamlit`

- [ ] **Step 2: Write the app**

Create `app.py`:

```python
"""Public dashboard over the audit log.

Deliberately read-only and credential-free. Nothing reachable from the public
internet can place an order; judges get interactivity through replay instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Options Alpha Agent", layout="wide")

LOGS = Path("logs")


@st.cache_data
def load(path: str) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


st.title("Options Alpha Agent")
st.caption(
    "Supervised-autonomy options agent. An LLM chooses the trades; a deterministic "
    "gate layer can veto every one of them. This page replays what happened."
)

files = sorted(LOGS.glob("session-*.jsonl"), reverse=True)
if not files:
    st.warning("No session logs found.")
    st.stop()

choice = st.sidebar.selectbox("Session", [f.name for f in files])
records = load(str(LOGS / choice))

step = st.slider("Replay to event", 1, len(records), len(records))
shown = records[:step]

vetoes = [r for r in shown if r["event"] == "gate_verdict" and not r.get("allowed")]
submits = [r for r in shown if r["event"] == "submission"]

c1, c2, c3 = st.columns(3)
c1.metric("Events", len(shown))
c2.metric("Orders submitted", len(submits))
c3.metric("Gate vetoes", len(vetoes))

if vetoes:
    st.subheader("Vetoes")
    for v in vetoes:
        st.error(" / ".join(v.get("reasons", [])))

st.subheader("Decision trail")
for r in shown:
    if r["event"] == "decision":
        st.markdown(f"**{r['timestamp']}**")
        st.write(r["reasoning"])
    elif r["event"] == "tool_call":
        st.code(f"{r['tool']}({json.dumps(r['input'])})", language="json")
    elif r["event"] == "gate_verdict":
        st.success("gates: allowed") if r.get("allowed") else st.error(
            "gates: vetoed / " + " / ".join(r.get("reasons", []))
        )
    elif r["event"] == "submission":
        st.info(f"submitted {r.get('order_id', '')}")
```

- [ ] **Step 3: Pin the theme**

Create `.streamlit/config.toml`:

```toml
[server]
headless = true

[browser]
gatherUsageStats = false
```

- [ ] **Step 4: Run it locally**

Run: `uv run streamlit run app.py`
Expected: the app opens, lists the session logs from Task 8, and the replay slider steps through them.

- [ ] **Step 5: Confirm the app has no credentials and no write path**

Run: `git grep -n "ALPACA_SECRET\|submit_order\|TradingClient" app.py || echo "clean"`
Expected: `clean`

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format .
git add app.py .streamlit/ pyproject.toml uv.lock
git commit -m "Add the read-only replay dashboard

The submission requires a public demo URL, and a public URL with order
authority on the judged account is precisely the scenario the no-unattended
-execution boundary exists to prevent. Judges get interactivity through
replaying a recorded session instead, and the page holds no credentials at
all, so there is nothing to leak and nothing to rate-limit."
```

---

### Task 10: Deploy, write-up, and cleanup

**Files:**
- Create: `README.md`
- Create: `docs/writeup.md`
- Delete: `probe_fills.py`, `check_account.py`, `mcp_smoke.py`, `chain.py`

**Interfaces:**
- Consumes: everything.
- Produces: the submission artifacts.

- [ ] **Step 1: Deploy to Streamlit Community Cloud**

Push the repository to a public GitHub remote, then at share.streamlit.io connect the repo and set the entry point to `app.py`. Add no secrets: the app reads only committed logs.

Record the resulting URL; it is a required submission field.

- [ ] **Step 2: Write the required one-page write-up**

Create `docs/writeup.md` with exactly three sections, per spec section 10:

- **AI logic:** what the model sees (account, positions, chain, quotes through 19 read-only MCP tools), what it can call (three write tools), how it chooses (moneyness, since Alpaca publishes no IV or greeks).
- **Risk gates:** the table from spec section 5, plus which gates actually fired during the week, taken from the audit logs.
- **Alpaca infrastructure:** MCP server for reads, `alpaca-py` for gated writes, paper environment, and the two paper behaviours that shaped the design (market orders fill, limit orders rest; and whatever Task 1 found about multi-leg).

State plainly that no edge is claimed and the strategy is a worked example.

- [ ] **Step 3: Write the README**

Create `README.md` covering: what this is, the safety model (single write path, gate table, kill switch, no scheduling), how to run a session, how to run the tests, and a link to the live dashboard.

- [ ] **Step 4: Delete the throwaway probes**

```bash
git rm probe_fills.py check_account.py mcp_smoke.py
```

Their findings live in `HANDOFF.md` section 4 and the spec; the scripts themselves were scaffolding.

- [ ] **Step 5: Scrub check before submission**

```bash
git grep -nE "PA[A-Z0-9]{8,}|PK[A-Z0-9]{16,}" -- . ':!uv.lock' || echo "no account numbers or keys in tracked files"
```
Expected: `no account numbers or keys in tracked files`

Also confirm `.env` is still ignored: `git check-ignore -v .env`

- [ ] **Step 6: Full verification**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/writeup.md
git commit -m "Add the submission write-up and remove the probe scripts

The probes were scaffolding for questions that are now answered, and their
findings live in HANDOFF.md section 4 and the design spec. Keeping the
scripts would leave four files in a public repository whose only purpose
was to tell us something we have since written down."
```

---

## Self-Review

**Spec coverage:** Section 4's six modules map to Tasks 2-9 (`gates.py` 2-4, `audit.py` 5, `broker.py` 6, `tools.py`/`session.py` 8, `app.py` 9); `mcp_tools.py` is Task 7 and is an addition the spec implied but did not name. Section 5's gate table is covered by Tasks 2-4. Section 6's session model is Task 8. Section 7's audit log is Task 5. Section 9's testing requirements including the mutation check are in Tasks 3 and 4. Section 10's write-up is Task 10. Section 11's keystone is Task 1, sequenced first and blocking. Section 12's out-of-scope list has no tasks, correctly.

**Gap found and closed:** the spec describes the MCP read/write split in prose but assigns it no module. Task 7 makes it a real component with its own tests, since it is the load-bearing part of the safety argument.

**Type consistency:** `VerticalOrder`, `Snapshot`, `OpenPosition`, `Limits`, `Verdict`, `check`, `position_key`, `worst_case_loss` and `filter_tools` keep the same signatures across Tasks 2-8. `open_vertical` is the tool name throughout, matching the spec after its rename from `propose_vertical`.
