"""Which account this process is allowed to touch.

Both accounts' keys live in the same .env, so selection has to be explicit in
code rather than done by hand-swapping values. A manual swap is a step someone
forgets, and the direction it fails in is the expensive one.

See HANDOFF.md boundary 6. The competition account must show a starting
balance of exactly $100,000 when judging opens, and judges read its activity
to score P&L, so nothing may fill on it before kickoff.
"""

from __future__ import annotations

import datetime as dt
import os

KICKOFF = dt.datetime(2026, 8, 28, 15, 0, tzinfo=dt.UTC)

ROLES = ("dev", "competition")

_KEYS = {
    "dev": ("DEV_API_KEY", "DEV_SECRET_KEY"),
    "competition": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
}


def resolve_credentials(now: dt.datetime | None = None) -> tuple[str, str, str]:
    """Return (api_key, secret_key, role) for the account this run may touch.

    Raises rather than guessing. There is deliberately no default role: with
    both accounts' keys present, defaulting to dev would let a forgotten
    variable trade the competition account silently, and defaulting to
    competition is worse. Unset fails closed.
    """
    now = now or dt.datetime.now(dt.UTC)

    paper = os.environ.get("ALPACA_PAPER_TRADE", "true").lower()
    if paper != "true":
        raise RuntimeError(f"ALPACA_PAPER_TRADE is {paper!r}, refusing: paper only")

    role = os.environ.get("ALPACA_ACCOUNT_ROLE")
    if not role:
        raise RuntimeError(
            f"ALPACA_ACCOUNT_ROLE is unset. Set it to one of {ROLES}; there is no default."
        )
    if role not in ROLES:
        raise RuntimeError(f"ALPACA_ACCOUNT_ROLE {role!r} is not one of {ROLES}")

    if role == "competition" and now < KICKOFF:
        raise RuntimeError(
            f"refusing the competition account before kickoff ({KICKOFF.isoformat()}). "
            f"It must show a $100,000 starting balance and an empty activity history "
            f"when judging opens. Use ALPACA_ACCOUNT_ROLE=dev until then."
        )

    key_var, secret_var = _KEYS[role]
    key = os.environ.get(key_var)
    secret = os.environ.get(secret_var)
    if not key:
        raise RuntimeError(f"{key_var} is unset but ALPACA_ACCOUNT_ROLE={role}")
    if not secret:
        raise RuntimeError(f"{secret_var} is unset but ALPACA_ACCOUNT_ROLE={role}")
    if not key.startswith("PK"):
        raise RuntimeError(f"{key_var} prefix {key[:2]!r} is not a paper key prefix")

    return key, secret, role
