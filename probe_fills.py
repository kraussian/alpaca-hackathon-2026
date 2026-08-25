"""Checklist item 4: confirm Alpaca paper's option fill behaviour on this account.

The handoff claims paper fills MARKET option orders only, and that LIMIT orders
rest unfilled indefinitely even when marketable. That claim shapes the whole
agent design, so it gets re-verified on the new account rather than trusted.

Dry run by default. Pass --trade to actually submit.
"""

import argparse
import datetime as dt
import os
import time

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import OptionLatestQuoteRequest, StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetStatus, ContractType, OrderSide, TimeInForce
from alpaca.trading.requests import (
    GetOptionContractsRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)
from dotenv import load_dotenv


def third_friday(year: int, month: int) -> dt.date:
    """Monthly expiry. Naive nearest-expiry logic picks dailies instead."""
    d = dt.date(year, month, 1)
    first_friday = d + dt.timedelta(days=(4 - d.weekday()) % 7)
    return first_friday + dt.timedelta(days=14)


def _self_check() -> None:
    assert third_friday(2026, 9) == dt.date(2026, 9, 18)
    assert third_friday(2026, 8) == dt.date(2026, 8, 21)
    assert third_friday(2026, 5) == dt.date(2026, 5, 15)  # month starts on a Friday
    assert third_friday(2027, 1) == dt.date(2027, 1, 15)


def next_monthly(today: dt.date, min_days: int = 10) -> dt.date:
    """First monthly expiry at least min_days out, so it is not about to expire."""
    y, m = today.year, today.month
    for _ in range(3):
        exp = third_friday(y, m)
        if (exp - today).days >= min_days:
            return exp
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    raise RuntimeError("no monthly expiry found")


def poll_status(tc: TradingClient, order_id, seconds: int) -> tuple[str, object]:
    """Poll until terminal or timeout. Returns (status, filled_avg_price)."""
    deadline = time.monotonic() + seconds
    while True:
        o = tc.get_order_by_id(order_id)
        status = str(o.status).split(".")[-1].lower()
        if status in {"filled", "canceled", "rejected", "expired"}:
            return status, o.filled_avg_price
        if time.monotonic() >= deadline:
            return status, o.filled_avg_price
        time.sleep(2)


def main() -> None:
    _self_check()
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade", action="store_true", help="actually submit orders")
    ap.add_argument("--underlying", default="SPY")
    ap.add_argument("--wait", type=int, default=45, help="seconds to poll each order")
    args = ap.parse_args()

    load_dotenv()
    assert os.environ.get("ALPACA_PAPER_TRADE", "true").lower() == "true", (
        "live refused"
    )
    key, sec = os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
    assert key.startswith("PK"), "not a paper key"

    tc = TradingClient(key, sec, paper=True)
    clock = tc.get_clock()
    print(f"market open: {clock.is_open}  (next open {clock.next_open})")

    spot = (
        StockHistoricalDataClient(key, sec)
        .get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=args.underlying)
        )[args.underlying]
        .price
    )
    exp = next_monthly(clock.timestamp.date())
    print(f"{args.underlying} spot {spot:.2f}   monthly expiry {exp} ({exp:%A})")

    contracts = tc.get_option_contracts(
        GetOptionContractsRequest(
            underlying_symbols=[args.underlying],
            status=AssetStatus.ACTIVE,
            type=ContractType.CALL,
            expiration_date=exp,
            strike_price_gte=str(round(spot * 0.98, 2)),
            strike_price_lte=str(round(spot * 1.02, 2)),
            limit=100,
        )
    ).option_contracts
    assert contracts, "no contracts in the moneyness band"
    c = min(contracts, key=lambda k: abs(k.strike_price - spot))
    assert c.expiration_date == exp, f"selected {c.expiration_date}, wanted {exp}"
    print(f"selected {c.symbol}  strike {c.strike_price}  exp {c.expiration_date}")

    q = OptionHistoricalDataClient(key, sec).get_option_latest_quote(
        OptionLatestQuoteRequest(symbol_or_symbols=c.symbol)
    )[c.symbol]
    print(f"quote bid {q.bid_price} ask {q.ask_price}  (as of {q.timestamp})")

    if not args.trade:
        print("\nDRY RUN. Re-run with --trade during market hours to probe fills.")
        return

    print("\n--- MARKET buy 1 ---")
    mo = tc.submit_order(
        MarketOrderRequest(
            symbol=c.symbol, qty=1, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
        )
    )
    status, px = poll_status(tc, mo.id, args.wait)
    print(f"market order -> {status}  filled_avg_price {px}")

    print("\n--- LIMIT buy 1 at the ask (marketable) ---")
    lo = tc.submit_order(
        LimitOrderRequest(
            symbol=c.symbol,
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            limit_price=float(q.ask_price),
        )
    )
    lstatus, lpx = poll_status(tc, lo.id, args.wait)
    print(f"limit order -> {lstatus}  filled_avg_price {lpx}")
    if lstatus not in {"filled", "canceled", "rejected", "expired"}:
        tc.cancel_order_by_id(lo.id)
        print("limit order cancelled")

    print(
        f"\nVERDICT: market={status}, marketable-limit={lstatus}. "
        f"Handoff claim {'HOLDS' if status == 'filled' and lstatus != 'filled' else 'DOES NOT HOLD'}."
    )


if __name__ == "__main__":
    main()
