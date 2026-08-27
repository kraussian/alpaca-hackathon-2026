"""The only file in this repository that can write to Alpaca.

Every mutating call routes through here and every one of them runs the gates
first. That is the whole safety argument: it is checkable by grepping for
submit_order and close_position, and it holds only as long as this stays the
single write path.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

from alpaca.common.exceptions import APIError
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import (
    OptionSnapshotRequest,
    StockLatestQuoteRequest,
    StockLatestTradeRequest,
)
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    AssetClass,
    OrderClass,
    OrderSide,
    PositionIntent,
    TimeInForce,
)
from alpaca.trading.requests import MarketOrderRequest, OptionLegRequest

from agent_pkg.accounts import resolve_credentials
from agent_pkg.audit import AuditLog
from agent_pkg.gates import (
    Limits,
    OpenPosition,
    Snapshot,
    Verdict,
    VerticalOrder,
    check,
    net_delta_notional,
    position_key,
    worst_case_loss,
)
from agent_pkg.positions import Leg, parse_occ, reconstruct

KILL_FILE = Path(".kill")


class Broker:
    def __init__(
        self,
        limits: Limits,
        audit: AuditLog,
        kill_file: Path = KILL_FILE,
        client: object | None = None,
        clock_is_open: bool | None = None,
        now: dt.datetime | None = None,
        option_data: object | None = None,
        stock_data: object | None = None,
    ) -> None:
        # Resolves which account this process may touch, and raises rather
        # than guessing. Done in __init__ so a misconfigured process dies
        # before it has an order to submit.
        key, secret, self.role = resolve_credentials(now=now)

        self.limits = limits
        self.audit = audit
        self.kill_file = Path(kill_file)
        self.key_prefix = key[:2]
        self._clock_override = clock_is_open
        self.client = client or TradingClient(key, secret, paper=True)
        # Read-only market data, used solely to price the risk of positions we
        # already hold. Separate clients because greeks live on the data API,
        # not the trading API.
        self.option_data = option_data or OptionHistoricalDataClient(key, secret)
        self.stock_data = stock_data or StockHistoricalDataClient(key, secret)
        self._open: list[OpenPosition] = []

    def _market_open(self) -> bool:
        if self._clock_override is not None:
            return self._clock_override
        return bool(self.client.get_clock().is_open)

    def snapshot(
        self, open_positions: tuple[OpenPosition, ...] | None = None
    ) -> Snapshot:
        return Snapshot(
            now=dt.datetime.now(dt.UTC),
            market_open=self._market_open(),
            kill_switch=self.kill_file.exists(),
            paper=True,
            key_prefix=self.key_prefix,
            open_positions=(
                open_positions if open_positions is not None else tuple(self._open)
            ),
        )

    def load_open_positions(self) -> tuple[OpenPosition, ...]:
        """Replace the in-memory book with what the account actually holds.

        Call this at session start. Without it `self._open` starts empty every
        run, so the aggregate loss gate, the book net delta gate and dedupe all
        measure only the current process. With a one-order-per-session cap the
        aggregate loss gate could never fire at all.

        Raises rather than substituting zero for anything it cannot price. A
        session that cannot see its own book's risk should not be opening
        positions, and there is a human present to retry.
        """
        held = [
            p
            for p in self.client.get_all_positions()
            if p.asset_class == AssetClass.US_OPTION
        ]
        if not held:
            self._open = []
            return ()

        symbols = [p.symbol for p in held]
        snapshots = self.option_data.get_option_snapshot(
            OptionSnapshotRequest(symbol_or_symbols=symbols)
        )
        roots = sorted({parse_occ(s)[0] for s in symbols})
        trades = self.stock_data.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=roots)
        )

        legs = []
        for position in held:
            greeks = getattr(snapshots.get(position.symbol), "greeks", None)
            delta = getattr(greeks, "delta", None)
            if delta is None:
                raise RuntimeError(
                    f"no delta available for held position {position.symbol}; "
                    f"refusing to start a session blind to its own book delta"
                )
            legs.append(
                Leg(
                    symbol=position.symbol,
                    qty=int(float(position.qty)),
                    avg_entry_price=float(position.avg_entry_price),
                    delta=float(delta),
                    underlying_price=float(trades[parse_occ(position.symbol)[0]].price),
                )
            )

        self._open = list(reconstruct(legs, dt.datetime.now(dt.UTC)))
        self.audit.write(
            "book_loaded",
            positions=[
                {
                    "key": p.key,
                    "worst_case_loss": p.worst_case_loss,
                    "net_delta_notional": p.net_delta_notional,
                }
                for p in self._open
            ],
            aggregate_loss=sum(p.worst_case_loss for p in self._open),
            net_delta_notional=sum(p.net_delta_notional for p in self._open),
        )
        return tuple(self._open)

    def equity(self) -> float | None:
        """Account equity, or None if it cannot be read.

        Logged at session start and end so the dashboard can show a real
        per-session P&L rather than a curve inferred from order prices.
        """
        try:
            return float(self.client.get_account().equity)
        except (APIError, AttributeError, TypeError, ValueError):
            # Cosmetic: this feeds the dashboard, so a broker outage or a stub
            # client must not take down a session that is otherwise fine.
            return None

    def underlying_mid(self, symbol: str) -> float | None:
        """Midpoint of the underlying's live quote, or None.

        The midpoint rather than the last trade. Outside regular hours, and on
        thin venues during them, the last print can sit dollars away from the
        book: QQQ printed 717.80 on a 40-share pre-market trade while the quote
        was 712.34/712.44, and the option chain's greeks were struck off the
        quote. Feeding the gate a price the deltas were not computed against
        misstates the delta notional it checks.
        """
        try:
            quotes = self.stock_data.get_stock_latest_quote(
                StockLatestQuoteRequest(symbol_or_symbols=[symbol])
            )
            bid = float(quotes[symbol].bid_price)
            ask = float(quotes[symbol].ask_price)
        except (APIError, KeyError, AttributeError, TypeError, ValueError):
            return None
        if bid <= 0 or ask <= 0 or ask < bid:
            return None
        return (bid + ask) / 2

    def open_vertical(self, order: VerticalOrder) -> dict:
        # underlying_price is the one input to a risk figure that the model
        # supplies and nothing verifies. net_delta_notional multiplies by it,
        # so a wrong ticker, a fat finger or a stale print silently moves the
        # number the book delta cap is checked against. Read it ourselves
        # instead of trusting it: the model proposes, the gate measures.
        extra: list[str] = []
        mid = self.underlying_mid(order.underlying)
        if mid is None:
            extra.append(
                f"could not read a live quote for {order.underlying}, so the "
                f"book delta figure cannot be verified"
            )
        else:
            if abs(mid - order.underlying_price) > 0.01:
                self.audit.write(
                    "underlying_price_corrected",
                    underlying=order.underlying,
                    supplied=order.underlying_price,
                    quote_mid=mid,
                )
            order = replace(order, underlying_price=mid)

        snap = self.snapshot()
        verdict = check(order, snap, self.limits)
        if extra:
            # Appended rather than short-circuited: check() collects every
            # reason on purpose so the model fixes all of them in one pass.
            verdict = Verdict(allowed=False, reasons=tuple(extra) + verdict.reasons)
        self.audit.write(
            "gate_verdict",
            allowed=verdict.allowed,
            reasons=list(verdict.reasons),
            order=vars(order),
        )
        if not verdict.allowed:
            return {
                "submitted": False,
                "reasons": list(verdict.reasons),
                "order_id": None,
            }

        request = MarketOrderRequest(
            qty=order.qty,
            order_class=OrderClass.MLEG,
            time_in_force=TimeInForce.DAY,
            legs=[
                OptionLegRequest(
                    symbol=order.long_symbol,
                    ratio_qty=1,
                    side=OrderSide.BUY,
                    position_intent=PositionIntent.BUY_TO_OPEN,
                ),
                OptionLegRequest(
                    symbol=order.short_symbol,
                    ratio_qty=1,
                    side=OrderSide.SELL,
                    position_intent=PositionIntent.SELL_TO_OPEN,
                ),
            ],
        )
        submitted = self.client.submit_order(request)
        self._open.append(
            OpenPosition(
                key=position_key(order),
                opened_at=snap.now,
                worst_case_loss=worst_case_loss(order),
                net_delta_notional=net_delta_notional(order),
            )
        )
        self.audit.write("submission", order_id=str(submitted.id), order=vars(order))
        return {"submitted": True, "reasons": [], "order_id": str(submitted.id)}

    def close_vertical(self, long_symbol: str, short_symbol: str) -> dict:
        """Close a vertical, short leg first.

        Order matters. Closing the long leg first leaves the short leg
        momentarily uncovered, and Alpaca rejects that with
        `40310000 account not eligible to trade uncovered option contracts`
        because level 3 cannot hold a naked short call. Measured 2026-08-25.
        """
        if self.kill_file.exists():
            reasons = ["kill switch is engaged"]
            self.audit.write("gate_verdict", allowed=False, reasons=reasons)
            return {"submitted": False, "reasons": reasons, "order_id": None}

        self.client.close_position(short_symbol)
        self.client.close_position(long_symbol)
        self.audit.write(
            "submission", action="close", short=short_symbol, long=long_symbol
        )
        # Resync rather than dropping the legs by hand. If the closing order
        # has not filled yet the position is still open, and a reload reports
        # it as such instead of quietly shrinking the book we gate against.
        self.load_open_positions()
        return {"submitted": True, "reasons": [], "order_id": None}
