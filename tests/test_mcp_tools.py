from agent_pkg.mcp_tools import READ_ONLY_TOOLS, filter_tools

# Every mutating tool the live Alpaca MCP server exposes, enumerated from it
# on 2026-08-25. Any one of these reaching the model is a write path that
# never touches broker.py.
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
