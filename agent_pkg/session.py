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
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from agent_pkg import tools as write_tools
from agent_pkg.accounts import resolve_credentials
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
   get_option_chain returns live greeks and implied volatility per contract.
3. Read the actual bid and ask on both legs. Pass the long leg's ask and the
   short leg's bid, not the mid. The gates compute worst-case risk from them.
4. Pass each leg's delta and the short leg's implied volatility straight from
   the chain snapshot. Do not estimate them.

Select strikes by delta, not by percentage moneyness. Delta is the better
instrument now that Alpaca publishes it: it already accounts for time to
expiry and implied volatility, which a fixed percentage does not.

Two greek limits are enforced. The short leg's delta is capped, so selling at
or inside the money is rejected. The book's net delta is capped in dollars of
underlying exposure, so several separately reasonable spreads cannot add up to
one large directional bet.

Implied volatility is yours to reason with and is recorded, but it is never a
veto. Whether the premium is worth the risk is your judgement, not a rule.

State your reasoning before each tool call. That reasoning is logged and is
the record of why this position exists.

You are not being scored on how many trades you place. If nothing looks worth
doing, say so and stop.
"""


def _mcp_env(key: str, secret: str) -> dict[str, str]:
    """Environment for the Alpaca MCP subprocess.

    The server reads ALPACA_API_KEY, which in .env is the competition account.
    The resolved credentials are substituted here so the model reads whichever
    account this session is actually allowed to touch, not whatever the file
    happens to name.
    """
    env = {k: v for k, v in os.environ.items() if v is not None}
    env["ALPACA_API_KEY"] = key
    env["ALPACA_SECRET_KEY"] = secret
    env["ALPACA_PAPER_TRADE"] = "true"
    return env


async def run_session(minutes: int, max_orders: int, underlyings: list[str]) -> None:
    session_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    audit = AuditLog(session_id=session_id)
    limits = Limits(allowed_underlyings=frozenset(underlyings))
    broker = Broker(limits=limits, audit=audit)
    write_tools.bind(broker, max_orders)

    key, secret, role = resolve_credentials()
    deadline = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=minutes)
    audit.write(
        "session_start",
        role=role,
        minutes=minutes,
        max_orders=max_orders,
        underlyings=underlyings,
        deadline=deadline.isoformat(),
        limits=vars(limits)
        | {"allowed_underlyings": sorted(limits.allowed_underlyings)},
    )
    print(f"session {session_id}  account role: {role}  deadline: {deadline:%H:%M UTC}")

    client = AsyncAnthropic()

    async with (
        stdio_client(
            StdioServerParameters(
                command="uvx", args=["alpaca-mcp-server"], env=_mcp_env(key, secret)
            )
        ) as (read, write),
        ClientSession(read, write) as mcp,
    ):
        await mcp.initialize()
        listed = (await mcp.list_tools()).tools
        allowed = filter_tools(listed)
        audit.write("mcp_tools", exposed=len(listed), allowed=[t.name for t in allowed])
        print(f"MCP: {len(listed)} tools exposed, {len(allowed)} allowed (read-only)")

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
                write_tools.close_vertical,
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

    audit.write(
        "session_end", orders_placed=write_tools.orders_placed(), log=str(audit.path)
    )
    print(f"\n{write_tools.orders_placed()} order(s) placed. Audit log: {audit.path}")
