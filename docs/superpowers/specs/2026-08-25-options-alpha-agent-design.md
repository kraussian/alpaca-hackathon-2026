# Options Alpha Agent: design

Written 2026-08-25, three days before kickoff. Governs the build for the Alpaca AI Trading Agents Hackathon (28 Aug to 4 Sep 2026). Read `HANDOFF.md` first; this document assumes its boundaries and does not restate them.

## 1. What we are building

A supervised-autonomy options trading agent. An LLM chooses the trades. A deterministic gate layer sits between the model's tool call and Alpaca and can veto any of them. A public dashboard replays the resulting audit log so judges can watch the agent work, including the vetoes.

The contribution is the gate layer, not the strategy. Per `HANDOFF.md` section 6 we ship the machinery and present the strategy as a worked example. No edge is claimed anywhere in the submission, because none has been measured.

## 2. Requirements this satisfies

Mandatory, from `HANDOFF.md` section 1. Each is a disqualifier, so each is traced to a component here.

| Requirement | Where it is satisfied |
| --- | --- |
| Autonomous AI trading agent on the Trading API | `agent.py` decides and submits without per-order approval |
| Alpaca MCP server or CLI | Alpaca MCP server supplies every read tool |
| All strategies incorporate options | The only permitted structures are option verticals |
| Brand-new paper account at exactly $100,000 | Done 2026-08-25, verified ACTIVE, options level 3 |
| Public GitHub repository | This repository |
| Deployed demo at a public URL | `app.py` on Streamlit Community Cloud |
| One-page write-up: AI logic, risk gates, Alpaca infrastructure | Section 10 |

## 3. Decisions and why

Four choices were made deliberately, and each closed off alternatives worth recording, because the reasons are not recoverable from the code.

**Supervised autonomy.** Inside a session the agent decides and trades on its own, with no per-order approval. The session is bounded and nothing survives it. Approval-gating every order was rejected: it is safer, but "autonomous agent" is a stated core requirement and a per-order approval queue reads as a recommender. Safety therefore comes from the gates and the kill switch rather than from a human clicking, which is also the more transferable result.

This accepts a thinner P&L ledger than a scheduled agent would produce, and P&L is judged. That trade is deliberate: a seven-day P&L sample is noise, and buying a marginally better number by weakening the safety story is a bad trade. Boundary 4 is not negotiable.

**The LLM decides; gates enforce.** The model receives account state, chain data and a tool belt, and picks the trade itself. The alternative, an LLM that emits a market read which deterministic code then converts into an order, was rejected because the model becomes decoration and it shows in a demo. It is also the shape the operator's existing quantitative system already has, so it would teach nothing new.

**Alpaca MCP for reads, our own tools for writes.** Alpaca's MCP server exposes 72 tools, order placement included. Handing the model that server directly would let it route around every gate, reducing the guardrail story to a slide. Reads come from Alpaca MCP, which satisfies the MCP requirement through genuine usage and inherits roughly sixty read tools we do not have to write. Writes go only through `broker.py`.

**Defined-risk verticals only.** Measured on 2026-08-25: a SPY covered call locks $76,365 of a $100,000 account in shares, so the account supports one position and the stock leg dominates the return, which is exactly what the kill ledger already found about the wheel. Verticals put the entire P&L in the options, cost the spread width per position, and have a maximum loss that is arithmetic rather than a guess, so a gate can prove it before submission. Section 5 of the handoff rates credit spreads weak on risk-adjusted return; we are not claiming an edge, and the write-up will say so plainly.

## 4. Components

Six modules. One invariant: exactly one file can write to Alpaca.

```
gates.py     pure functions, zero I/O. (order, snapshot) -> Allow | Veto(reason)
broker.py    the only Alpaca write path. Calls gates first. Refuses non-paper.
tools.py     the model's write tools: open_vertical, close_position, kill_switch
agent.py     session loop. Claude tool use. Alpaca MCP reads plus tools.py writes.
audit.py     append-only JSONL of every decision, tool call, verdict and fill
app.py       Streamlit dashboard and replay over the audit log
```

`gates.py` takes no account object, opens no socket and calls no model. That is what makes the safety-critical logic the easiest thing in the repository to test, and it is the reason for the split.

## 5. The gate layer

Every gate returns a verdict and a human-readable reason. The reason is returned to the model, which may retry. Vetoes are logged whether or not the model retries.

| Gate | Rule |
| --- | --- |
| Paper only | Key starts `PK`, client constructed `paper=True`, and `ALPACA_PAPER_TRADE` is `true`. All three, or refuse. |
| Structure | Exactly two legs, same underlying, same expiry, same option type, opposing sides. |
| Expiry | At least 10 days out, and equal to the third Friday of its month. |
| Per-position loss | Worst-case defined loss at or below `max_loss_per_position`. |
| Aggregate loss | Worst-case defined loss across all open positions at or below `max_aggregate_loss`. |
| Order size | Contracts at or below `max_contracts`. |
| Allowlist | Underlying in `allowed_underlyings`. |
| Kill switch | A sentinel file, checked before every write. Present means refuse. |
| Market hours | Refuse outside regular trading hours. |
| Dedupe | Refuse an identical spread opened within `dedupe_minutes`. |

Worst-case loss is computed pessimistically: assume the long leg pays the ask and the short leg receives the bid. For a debit spread, loss is the net debit times 100 times quantity. For a credit spread, it is width minus net credit, times 100 times quantity. Using the worst side of the quote rather than the mid means the gate cannot be defeated by a spread widening between check and fill.

Limits live in one dataclass with defaults, overridable per session. Starting values, to be tuned once the agent has run: `max_contracts` 5, `max_loss_per_position` $2,000, `max_aggregate_loss` $10,000, `min_days_to_expiry` 10, `dedupe_minutes` 30, `allowed_underlyings` SPY, QQQ, IWM. These are a starting point, not a result.

## 6. Session model

```
uv run python -m agent --minutes 60 --max-orders 3
```

Two independent stop conditions, wall clock and order count, because either alone fails open if the other is misconfigured. The process exits when it stops. Nothing is scheduled, nothing survives the session, per boundary 4.

The kill switch is a file rather than a signal so it can be tripped from another terminal, or by the operator, without finding and killing the process.

## 7. Audit log

One JSONL record per event, appended, never rewritten. Fields: timestamp, session id, event type (`decision`, `tool_call`, `gate_verdict`, `submission`, `fill`, `error`), the model's stated reasoning, the full proposal, every gate verdict with its reason, and the broker response.

Account numbers are scrubbed at write time, not before submission. Boundary 5 says assume anything submitted is public, and this log is going into a public repository to feed the dashboard.

This log is the demo. It is also the only record of why the agent did what it did, so it is written before the order is submitted, not after the fill.

## 8. Dashboard

Streamlit Community Cloud, deployed from the public repository, holding no Alpaca credentials. It reads committed audit logs and renders the decision sequence, the model's reasoning, each gate verdict, fills and a P&L curve. A replay control steps through a recorded session.

Judges get interactivity through replay rather than through live authority. Nothing reachable from the public internet can place an order. A public URL with order authority on the judged account is the precise scenario boundary 4 exists to prevent.

`.gitignore` currently excludes `*.jsonl`, which will hide the audit logs the dashboard needs. Narrow that rule to the paths that actually warrant it.

## 9. Testing

`test_gates.py` is a real test file, not a self-check. Each gate gets an allow case, a veto case, and its boundary: exactly at the limit, and one past it. Section 8 of the handoff makes guardrails the explicit exception to hackathon corner-cutting, and `gates.py` being pure means these tests need no network, no account and no model.

Everything else gets an `assert` self-check. `third_friday` already has one in `probe_fills.py`. It moves into `gates.py`, since the expiry gate is its real consumer and `probe_fills.py` is throwaway.

Mutation check before we trust the suite: break each limit comparison by one and confirm a test fails. A gate test that passes with the gate removed is worse than no test, because it manufactures confidence.

## 10. Write-up

One page, the required deliverable, three parts. AI logic: what the model sees, what it can call, how it chooses. Risk gates: the table in section 5, and honestly which ones have fired in practice. Alpaca infrastructure: MCP for reads, alpaca-py for gated writes, the paper environment, and the two paper behaviours in handoff section 4 that shaped the design.

It states that no edge is claimed and that the strategy is a worked example.

## 11. Open risk

**The keystone is unverified.** This design assumes Alpaca paper fills a market multi-leg order. Handoff section 4 establishes that paper fills market single-leg orders and that limit orders rest unfilled indefinitely, but it says nothing about multi-leg, and that finding is from July on a different account. `alpaca-py` permits `OrderClass.MLEG` with market or limit type, which settles the SDK layer and not the paper engine.

Tripwire: extend `probe_fills.py` to submit one market vertical at the opening bell, before any other work starts. Fallbacks, in order: marketable limit; then sequential single legs with a gate bounding the unhedged window. If neither fills, the structure decision in section 3 reopens and this document is wrong.

Do not build on top of this assumption until the probe has run.

## 12. Out of scope

Deliberately not built, so the omissions are decisions rather than oversights: backtesting (no IV, no greeks and no NBBO history on Alpaca, so it cannot be done honestly), strategy optimisation, any port of `alpaca-trader` code, live trading support of any kind, scheduling, and multi-account support.
