"""Read-only filter over Alpaca's MCP tools.

Alpaca's MCP server exposes order placement, position closing and order
cancellation in the same tool list as its market data endpoints. Handing the
model the unfiltered list would give it a write path that never touches
broker.py, and every gate in this repository would become decoration.

This is an allowlist and must stay one. A denylist is correct only until
Alpaca ships a tool nobody here has heard of, and it fails open on that day.
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
