"""Write tools exposed to the model. Every one routes through the broker.

These are async because the session runs on AsyncAnthropic, and the async tool
runner needs BetaAsyncFunctionTool. Sync @beta_tool functions produce
BetaFunctionTool, which the async runner cannot convert and which surfaces as
a JSON serialization TypeError rather than anything that names the problem.

The broker calls are blocking HTTP, so they run in a thread. The same event
loop is servicing the MCP server's stdio pipes, and stalling it for the length
of an order submission is a good way to produce a mystery later.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from anthropic import beta_async_tool

from agent_pkg.gates import VerticalOrder

_BROKER = None
_STATE = {"orders": 0, "max_orders": 0}


def bind(broker, max_orders: int) -> None:
    global _BROKER
    _BROKER = broker
    _STATE["orders"] = 0
    _STATE["max_orders"] = max_orders


def orders_placed() -> int:
    return _STATE["orders"]


@beta_async_tool
async def open_vertical(
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
    long_delta: float,
    short_delta: float,
    short_iv: float,
    underlying_price: float,
) -> str:
    """Open a defined-risk vertical spread.

    Every order passes the risk gates first and may be vetoed. A veto comes
    back to you with its reasons so you can propose something else.

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
        long_delta: Delta of the long leg, from the chain snapshot.
        short_delta: Delta of the short leg, from the chain snapshot. Selling
            at or inside the money is rejected.
        short_iv: Implied volatility of the short leg, from the chain snapshot.
            Logged for the record; never used to veto.
        underlying_price: Current price of the underlying. The book's net delta
            limit is denominated in dollars of underlying exposure.
    """
    if _STATE["orders"] >= _STATE["max_orders"]:
        return f"VETO: session order cap of {_STATE['max_orders']} already reached"

    try:
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
            long_delta=long_delta,
            short_delta=short_delta,
            short_iv=short_iv,
            underlying_price=underlying_price,
        )
    except ValueError as exc:
        return f"VETO: could not read the order: {exc}"

    result = await asyncio.to_thread(_BROKER.open_vertical, order)
    if not result["submitted"]:
        return "VETO: " + "; ".join(result["reasons"])
    _STATE["orders"] += 1
    return f"SUBMITTED order {result['order_id']}"


@beta_async_tool
async def close_vertical(long_symbol: str, short_symbol: str) -> str:
    """Close an open vertical spread.

    Pass both legs. The broker closes the short leg first, because closing the
    long leg first leaves the short leg uncovered and the account cannot hold
    an uncovered short option.

    Args:
        long_symbol: OCC symbol of the long leg.
        short_symbol: OCC symbol of the short leg.
    """
    result = await asyncio.to_thread(_BROKER.close_vertical, long_symbol, short_symbol)
    return "CLOSED" if result["submitted"] else "VETO: " + "; ".join(result["reasons"])


@beta_async_tool
async def engage_kill_switch(reason: str) -> str:
    """Stop all trading for the rest of this session.

    Use this if account state looks wrong or you are not confident it is safe
    to continue. Nothing you do afterwards will reach the broker.

    Args:
        reason: Why you are stopping.
    """
    _BROKER.kill_file.write_text(reason, encoding="utf-8")
    _BROKER.audit.write("kill_switch", reason=reason)
    return f"KILL SWITCH ENGAGED: {reason}"
