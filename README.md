# Options Alpha Agent

A supervised-autonomy options trading agent for the Alpaca AI Trading Agents Hackathon.

An LLM chooses defined-risk option verticals. A deterministic gate layer sits between its tool call and the broker and can veto any of them. Every decision, every gate verdict and every fill is written to an append-only audit log, which a public dashboard replays.

**The contribution is the gate layer, not the strategy.** No edge is claimed. See [`docs/writeup.md`](docs/writeup.md).

## Safety model

1. **One write path.** `agent_pkg/broker.py` is the only file that can write to Alpaca, and every mutating call runs the gates first. Checkable by grep.
2. **The model cannot route around it.** Alpaca's MCP server exposes 72 tools including order placement and position closing. The model gets an explicit allowlist of 19 read-only tools; a denylist would fail open the day Alpaca adds a tool.
3. **Pure gates.** `agent_pkg/gates.py` takes no account, opens no socket, calls no model. 81 tests, boundary cases mutation-checked.
4. **Two accounts, enforced in code.** `ALPACA_ACCOUNT_ROLE` has no default; unset is an error. The competition account is unreachable before kickoff.
5. **Kill switch.** A sentinel file checked before every write, trippable from another terminal without finding the process.
6. **Nothing scheduled.** No cron, no timer, no loop that survives the session. Two independent stop conditions, wall clock and order count.
7. **Paper only.** Key prefix, client mode and environment flag all checked, at construction time.

## Running a session

```bash
uv sync
cp .env.example .env      # then fill in keys; ALPACA_ACCOUNT_ROLE=dev
uv run python -m agent_pkg --minutes 30 --max-orders 1 --underlyings SPY QQQ IWM
```

Watch it. To abort from another terminal:

```bash
echo stop > .kill
```

## Dashboard

```bash
uv run streamlit run app.py
```

Read-only. Holds no credentials and has no code path to a broker.

## Tests

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

## Calibrating the limits

```bash
uv run python calibrate_limits.py
```

Reports what fraction of the real option chain each risk limit admits, and how smoothly that responds as a limit moves. It references no P&L, so it cannot be overfitted to returns. Re-run after changing any limit in `agent_pkg/gates.py`.

## Layout

```
agent_pkg/
  accounts.py    which account this process may touch; no default, fails closed
  gates.py       pure risk gates: the deliverable
  positions.py   rebuilds the open book from the account, so aggregate gates see it
  broker.py      the only Alpaca write path
  mcp_tools.py   read-only allowlist over Alpaca's MCP server
  tools.py       the model's three write tools
  session.py     one bounded, supervised session
app.py           read-only replay dashboard
docs/writeup.md  AI logic, risk gates, Alpaca infrastructure
HANDOFF.md       hard boundaries and hard-won Alpaca facts
logs/            audit logs, scrubbed at write time
```
