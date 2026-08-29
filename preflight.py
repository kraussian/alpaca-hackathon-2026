"""Read-only check of everything that has to be true before a live session.

Run it before every session. It touches no write path: it resolves credentials
through the same fail-closed function the session uses, then reads the account
and the clock. Nothing here can place, cancel or close an order.

The account number is never printed. It goes in the submission form only.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from alpaca.trading.client import TradingClient
from dotenv import load_dotenv

from agent_pkg.accounts import resolve_credentials
from agent_pkg.broker import KILL_FILE


def main() -> None:
    load_dotenv(".env")
    key, secret, role = resolve_credentials()
    client = TradingClient(key, secret, paper=True)
    account = client.get_account()
    clock = client.get_clock()
    positions = client.get_all_positions()
    orders = client.get_orders()

    # Alpaca returns clock times in US/Eastern. They are tz-aware, so the
    # arithmetic is right either way, but printing one without converting
    # labels 09:30 Eastern as 09:30 UTC and puts you at your desk four hours
    # early. SGT is a fixed +8 with no DST, so it needs no tz database.
    sgt = dt.timezone(dt.timedelta(hours=8), "SGT")

    def stamp(when: dt.datetime) -> str:
        return f"{when.astimezone(dt.UTC):%a %H:%M} UTC / {when.astimezone(sgt):%a %H:%M} SGT"

    now = dt.datetime.now(dt.UTC)
    print(f"now           {stamp(now)}")
    print(f"role          {role}   (key {key[:2]}..., paper)")
    print(
        f"account       {account.status}   options level {account.options_approved_level}"
    )
    print(f"equity        {account.equity}   cash {account.cash}")
    print(f"open          {len(positions)} positions, {len(orders)} live orders")

    if clock.is_open:
        closes_in = (clock.next_close - now).total_seconds() / 60
        print(f"market        OPEN, closes in {closes_in:.0f} min")
    else:
        opens_in = (clock.next_open - now).total_seconds() / 3600
        print(
            f"market        CLOSED, opens in {opens_in:.1f} h ({stamp(clock.next_open)})"
        )

    kill = Path(KILL_FILE)
    print(
        f"kill switch   {'PRESENT - the session will refuse to write' if kill.exists() else 'clear'}"
    )

    if role != "competition":
        print(
            "\nNOTE: role is not 'competition'. This session will not count for judging."
        )
    if not clock.is_open:
        print("\nNOTE: market is closed. The market-hours gate will veto every order.")


if __name__ == "__main__":
    main()
