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


def position_key(order: VerticalOrder) -> str:
    """Identity of a spread, ignoring size.

    Two fills of the same spread at different quantities are the same position
    for dedupe purposes.
    """
    lo, hi = sorted((order.long_strike, order.short_strike))
    return f"{order.underlying}:{order.expiry:%Y%m%d}:{order.option_type}:{lo:g}-{hi:g}"


def check(order: VerticalOrder, snapshot: Snapshot, limits: Limits) -> Verdict:
    """Run every gate and collect all reasons.

    Deliberately does not short-circuit. The reasons go back to the model, and
    one round-trip per problem wastes a supervised session.
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

    monthly = third_friday(order.expiry.year, order.expiry.month)
    if order.expiry != monthly:
        reasons.append(f"expiry {order.expiry} is not the third Friday ({monthly})")
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
