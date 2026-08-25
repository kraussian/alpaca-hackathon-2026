"""Measure how often each gate limit binds against the real option chain.

Risk limits cannot be backtested into robustness; tuning them against returns
would be the overfit. What can be measured is how much of the real chain each
limit admits, and whether that response is smooth or sits on a cliff. Neither
quantity references P&L, so neither can be fitted to it.

Re-run after moving any limit in the design spec section 5.
"""

import datetime as dt
import itertools
import os
import statistics
from collections import defaultdict

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import OptionLatestQuoteRequest, StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetStatus, ContractType
from alpaca.trading.requests import GetOptionContractsRequest
from dotenv import load_dotenv

load_dotenv(".env")
K, S = os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
tc = TradingClient(K, S, paper=True)
sd = StockHistoricalDataClient(K, S)
od = OptionHistoricalDataClient(K, S)


def third_friday(y, m):
    d = dt.date(y, m, 1)
    return d + dt.timedelta(days=(4 - d.weekday()) % 7) + dt.timedelta(days=14)


exp = third_friday(2026, 9)
rows = []
for u in ["SPY", "QQQ", "IWM"]:
    spot = sd.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=u))[
        u
    ].price
    for typ in (ContractType.CALL, ContractType.PUT):
        cs = tc.get_option_contracts(
            GetOptionContractsRequest(
                underlying_symbols=[u],
                status=AssetStatus.ACTIVE,
                type=typ,
                expiration_date=exp,
                strike_price_gte=str(round(spot * 0.95, 2)),
                strike_price_lte=str(round(spot * 1.05, 2)),
                limit=500,
            )
        ).option_contracts
        if not cs:
            continue
        q = od.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=[c.symbol for c in cs])
        )
        byk = {c.strike_price: c.symbol for c in cs}
        strikes = sorted(byk)
        for lo, hi in itertools.combinations(strikes, 2):
            w = round(hi - lo, 2)
            if w > 10.5:
                continue
            a, b = q.get(byk[lo]), q.get(byk[hi])
            if not a or not b or not a.ask_price or not b.bid_price:
                continue
            # both orientations: long lower / long upper
            for long_leg, short_leg in ((a, b), (b, a)):
                net = (
                    long_leg.ask_price - short_leg.bid_price
                )  # worst-case: pay ask, receive bid
                loss_per = net * 100 if net > 0 else (w - abs(net)) * 100
                if loss_per <= 0:
                    continue
                rows.append({"u": u, "w": w, "loss1": loss_per, "credit": net < 0})
print(f"verticals priced: {len(rows)}  underlyings: SPY/QQQ/IWM  expiry {exp}")
print(
    f"per-contract worst-case loss: median ${statistics.median(r['loss1'] for r in rows):,.0f}  "
    f"p10 ${statistics.quantiles([r['loss1'] for r in rows], n=10)[0]:,.0f}  "
    f"p90 ${statistics.quantiles([r['loss1'] for r in rows], n=10)[8]:,.0f}"
)

print(
    "\nadmissible fraction by (max_loss_per_position, qty)  -- how much of the chain survives the loss gate"
)
print(f"{'cap':>8} " + "".join(f"{'q' + str(q):>9}" for q in (1, 2, 3, 5)))
for cap in (500, 1000, 1500, 2000, 3000, 5000):
    cells = []
    for qty in (1, 2, 3, 5):
        ok = sum(1 for r in rows if r["loss1"] * qty <= cap)
        cells.append(f"{100 * ok / len(rows):>8.0f}%")
    print(f"${cap:>7,} " + "".join(cells))

print("\nmax reachable qty under each cap (is max_contracts alive?)")
for cap in (1000, 2000, 3000, 5000):
    reach = defaultdict(int)
    for r in rows:
        for qty in (1, 2, 3, 5):
            if r["loss1"] * qty <= cap:
                reach[qty] += 1
    tot = len(rows)
    print(
        f"  cap ${cap:>5,}: "
        + "  ".join(f"q{q} {100 * reach[q] / tot:.0f}%" for q in (1, 2, 3, 5))
    )

print("\nconcurrent positions allowed = aggregate / per-position")
for agg in (10000, 15000, 20000, 25000):
    for per in (1000, 1500, 2000):
        print(f"  agg ${agg:>6,} / per ${per:>5,} -> {agg // per} concurrent", end="")
    print()
