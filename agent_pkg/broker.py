"""The only file in this repository that can write to Alpaca.

Every mutating call routes through here and every one of them runs the gates
first. That is the whole safety argument: it is checkable by grepping for
submit_order and close_position, and it holds only as long as this stays the
single write path.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, PositionIntent, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, OptionLegRequest

from agent_pkg.accounts import resolve_credentials
from agent_pkg.audit import AuditLog
from agent_pkg.gates import (
    Limits,
    OpenPosition,
    Snapshot,
    VerticalOrder,
    check,
    net_delta_notional,
    position_key,
    worst_case_loss,
)

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

    def open_vertical(self, order: VerticalOrder) -> dict:
        snap = self.snapshot()
        verdict = check(order, snap, self.limits)
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
        return {"submitted": True, "reasons": [], "order_id": None}
