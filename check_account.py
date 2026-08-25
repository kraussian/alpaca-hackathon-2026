"""Read-only sanity check on the hackathon paper account. Prints no secrets."""

import os

from alpaca.trading.client import TradingClient
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    paper = os.environ.get("ALPACA_PAPER_TRADE", "true").lower() == "true"
    assert paper, "refusing to run against live"
    key = os.environ["ALPACA_API_KEY"]
    assert key.startswith("PK"), f"key prefix {key[:2]!r} is not a paper key"

    a = TradingClient(key, os.environ["ALPACA_SECRET_KEY"], paper=True).get_account()
    for f in (
        "status",
        "equity",
        "cash",
        "buying_power",
        "options_approved_level",
        "options_trading_level",
        "options_buying_power",
        "short_market_value",
        "pattern_day_trader",
        "trading_blocked",
    ):
        print(f"{f:24} {getattr(a, f, '<absent>')}")


if __name__ == "__main__":
    main()
