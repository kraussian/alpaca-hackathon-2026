"""Rebuild the open book from what the broker actually holds.

The aggregate gates in `gates.py` read `Snapshot.open_positions`. Until this
module existed, that tuple was populated only by orders placed in the current
process, so every session started believing the book was empty: the aggregate
loss gate summed to $0, the book net delta gate summed to $0, and dedupe could
not see a spread opened by the session before it. With a one-order cap per
session the aggregate loss gate was not merely weak, it was unreachable.

Pure by the same rule as `gates.py`: legs arrive as arguments. The network
lives in `broker.py`.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass, replace

from agent_pkg.gates import (
    OpenPosition,
    VerticalOrder,
    net_delta_notional,
    position_key,
    worst_case_loss,
)

# OCC symbol, as Alpaca returns it: root, YYMMDD, C or P, strike in
# thousandths. Alpaca does not space-pad the root to six characters the way
# the raw OCC standard does, so this matches the unpadded form.
_OCC = re.compile(r"([A-Z]+)(\d{6})([CP])(\d{8})")


@dataclass(frozen=True)
class Leg:
    """One option leg as held, not as quoted.

    `qty` is signed: negative is short. `avg_entry_price` is positive on both
    sides, being the premium paid or received per share.
    """

    symbol: str
    qty: int
    avg_entry_price: float
    delta: float
    underlying_price: float


def parse_occ(symbol: str) -> tuple[str, dt.date, str, float]:
    """(underlying, expiry, option_type, strike) from an OCC symbol."""
    m = _OCC.fullmatch(symbol)
    if not m:
        raise ValueError(f"{symbol!r} is not an OCC option symbol")
    root, ymd, cp, strike = m.groups()
    return (
        root,
        # OCC carries a two-digit year; expiries are dates, not instants.
        dt.date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:])),
        "call" if cp == "C" else "put",
        int(strike) / 1000,
    )


def _as_vertical(
    long_leg: Leg,
    short_leg: Leg,
    qty: int,
    underlying: str,
    expiry: dt.date,
    option_type: str,
    long_strike: float,
    short_strike: float,
) -> VerticalOrder:
    """A held spread in the shape the gate helpers already understand.

    The quote fields carry entry prices rather than live quotes, which is what
    we want: `net_debit` is documented as the cost at the worst fill, and the
    fill already happened. Reusing `position_key`, `worst_case_loss` and
    `net_delta_notional` rather than restating their arithmetic keeps one
    source of truth. That matters most for the key: a key computed a second
    way that disagrees by a digit would make dedupe silently never match.
    """
    return VerticalOrder(
        underlying=underlying,
        expiry=expiry,
        option_type=option_type,
        long_symbol=long_leg.symbol,
        short_symbol=short_leg.symbol,
        long_strike=long_strike,
        short_strike=short_strike,
        long_ask=long_leg.avg_entry_price,
        short_bid=short_leg.avg_entry_price,
        qty=qty,
        long_delta=long_leg.delta,
        short_delta=short_leg.delta,
        short_iv=0.0,  # unused by the three helpers; never gated on
        underlying_price=long_leg.underlying_price,
    )


def reconstruct(legs: list[Leg], now: dt.datetime) -> tuple[OpenPosition, ...]:
    """Pair held legs into verticals and price their risk.

    `opened_at` is set to `now` for every loaded position, because Alpaca's
    position objects carry no open timestamp. The effect is that a spread we
    already hold cannot be reopened for `dedupe_minutes` after session start,
    which errs toward refusing a duplicate rather than allowing one. Reading
    the true fill time would mean walking order history per leg; the cheap
    version is wrong only in the safe direction.
    """
    parsed = {leg.symbol: parse_occ(leg.symbol) for leg in legs}
    groups: dict[tuple[str, dt.date, str], list[Leg]] = defaultdict(list)
    for leg in legs:
        underlying, expiry, option_type, _ = parsed[leg.symbol]
        groups[(underlying, expiry, option_type)].append(leg)

    out: list[OpenPosition] = []
    for (underlying, expiry, option_type), group in sorted(groups.items()):
        longs = sorted((leg for leg in group if leg.qty > 0), key=lambda x: x.symbol)
        shorts = sorted((leg for leg in group if leg.qty < 0), key=lambda x: x.symbol)

        while longs and shorts:
            long_leg, short_leg = longs.pop(0), shorts.pop(0)
            qty = min(long_leg.qty, -short_leg.qty)
            order = _as_vertical(
                long_leg,
                short_leg,
                qty,
                underlying,
                expiry,
                option_type,
                parsed[long_leg.symbol][3],
                parsed[short_leg.symbol][3],
            )
            out.append(
                OpenPosition(
                    key=position_key(order),
                    opened_at=now,
                    worst_case_loss=worst_case_loss(order),
                    net_delta_notional=net_delta_notional(order),
                )
            )
            # A partial close can leave one side larger than the other. Put
            # the remainder back so it is either paired again or accounted
            # for as a leftover, never dropped.
            if long_leg.qty > qty:
                longs.insert(0, replace(long_leg, qty=long_leg.qty - qty))
            if -short_leg.qty > qty:
                shorts.insert(0, replace(short_leg, qty=short_leg.qty + qty))

        if shorts:
            # Level 3 cannot hold an uncovered short, and `close_vertical`
            # closes the short leg first precisely so this cannot arise from
            # our own close path. If it happened anyway the account is in a
            # state this code does not model, and the worst case is not a
            # number we can honestly put in the aggregate. Refuse the session.
            raise RuntimeError(
                f"uncovered short leg(s) {[leg.symbol for leg in shorts]} on the "
                f"account; refusing to compute a book risk figure for a position "
                f"whose worst case is unbounded"
            )

        for leg in longs:
            # A long leg on its own can lose only what it cost.
            out.append(
                OpenPosition(
                    key=f"{underlying}:{expiry:%Y%m%d}:{option_type}:{leg.symbol}",
                    opened_at=now,
                    worst_case_loss=leg.avg_entry_price * 100 * leg.qty,
                    net_delta_notional=(
                        leg.delta * 100 * leg.qty * leg.underlying_price
                    ),
                )
            )

    return tuple(out)
