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
