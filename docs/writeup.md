# Options Alpha Agent

An LLM chooses the trades. A deterministic gate layer sits between its tool call and the broker and can veto any of them. The contribution is the gate layer, not the strategy.

## AI logic

Claude Opus 5 runs a bounded session with a tool belt. Reads come from Alpaca's MCP server; writes go only through our own gated tools.

Each decision cycle: read the account and open positions, read the underlying and the monthly (third Friday) option chain, read the actual bid and ask on both legs, then propose a defined-risk vertical. Strikes are selected by **delta**, not percentage moneyness, because delta already prices in time to expiry and implied volatility. The model passes each leg's delta and the short leg's IV straight from the chain snapshot rather than estimating them.

The model is told explicitly that it is not scored on trade count. In its first session it read the chain, priced five candidate spreads, and declined all of them, giving its reasoning: 8-15% credit-to-width, a short strike inside the 1σ expected move, and skew running against the structure. Declining is a valid outcome and the log records why.

Worst-case risk is always computed from the **worst side** of the quote: pay the long leg's ask, receive the short leg's bid. The model is instructed to pass those, not the mid. Underwriting the pessimistic case means price improvement lands in our favour instead of walking a position past its limit. In the session that traded, the spread filled at $0.69 credit against the $0.64 the gates had underwritten.

## Risk gates

`gates.py` is pure: no network, no account object, no model. Everything arrives as an argument, which is why the safety-critical logic is the easiest thing in the repository to test. 81 tests, and the boundary tests are mutation-checked.

| Gate | Rule |
| --- | --- |
| Paper only | Key prefix `PK`, client in paper mode, and `ALPACA_PAPER_TRADE=true`. All three. |
| Account role | `dev` or `competition`, no default. The competition account is unreachable before kickoff. |
| Structure | Exactly two legs, same underlying, same expiry, same type, opposing sides. |
| Expiry | At least 10 days out **and** equal to the third Friday. |
| Quote sanity | Net price must sit inside the spread width; a crossed or stale quote is rejected before any risk number is trusted. |
| Per-position loss | Worst-case defined loss at or below $1,500. |
| Aggregate loss | Worst-case loss across the whole book at or below $15,000. |
| Order size | At or below 5 contracts. |
| Allowlist | Underlying in {SPY, QQQ, IWM}. |
| Delta sanity | Each leg's delta within [-1, 1], correctly signed for calls and puts. |
| Short delta | `abs(short_delta)` at or below 0.50; rejects selling at or inside the money. |
| Book net delta | Signed sum of delta exposure within $50,000 of underlying. |
| Book loaded | Open positions are read from the account at session start, not remembered in-process. |
| Kill switch | A sentinel file, checked before every write. |
| Market hours | Refuse outside regular trading hours. |
| Dedupe | Refuse an identical spread opened within 30 minutes. |

**Which gates actually fired.** The per-position loss gate vetoed a real order: the model proposed 4 lots of a 10-wide QQQ call spread risking $3,496, having sized to a 3.5%-of-equity heuristic it invented rather than the book's rule. The veto and its reason went back to the model, which restructured to 3 lots of a 5-wide at $1,308 and passed. Its own words in the log: *"the gate was right and I was wrong."* The kill switch was verified separately against a live account, with a negative control confirming the same order passes once the sentinel is removed.

**The aggregate gates had to be taught to see the account.** They read a list of
open positions, and that list was populated only by orders placed in the current
process. Every session therefore started believing the book was empty: aggregate
loss summed to $0, book net delta summed to $0, and dedupe could not see a spread
opened by the previous session. With a one-order-per-session cap the aggregate loss
gate was not merely weak, it was unreachable, because one position cannot exceed
$15,000 when each is capped at $1,500. `positions.py` now rebuilds the book from
what the account actually holds: it parses OCC symbols, pairs legs into verticals,
and prices each one from its entry fills and live greeks. Verified against the dev
account with a negative control, an order that passes against an empty book and is
vetoed once the real $1,293 position is loaded.

It refuses rather than guessing in two places. If a leg's delta cannot be read the
session does not start, because a session blind to its own directional exposure
should not be opening positions. If an uncovered short leg appears, which level 3
cannot hold and our short-leg-first close path cannot produce, it raises instead of
putting an unbounded worst case into an aggregate.

**Two design decisions worth stating.**

The loss and delta gates are **backstops, not shapers**. Measured against 6,375 real verticals, median worst-case loss per contract is $282 against a $1,500 cap, so the gate is silent in normal operation. That is correct behaviour for a backstop, not a dead limit. The gates that shape behaviour are the categorical ones: structure, expiry, allowlist, dedupe.

There is deliberately **no implied-volatility gate**, though IV is available and the model uses it. An IV floor is predictive gating on premia, which we had already adjudicated as harmful. IV reaches the model and the audit log; it never vetoes. Whether the premium justifies the risk is the model's judgement, and the record of that judgement is the point.

**Limits are derived, not tuned.** Aggregate loss comes from a stated 15% drawdown tolerance; per-position follows from wanting ~10 concurrent slots. Sensitivity was measured rather than assumed: at three contracts, moving the per-position cap $1,000 → $2,000 → $3,000 shifts chain admissibility 58% → 90% → 99%, smoothly, with no cliff. `calibrate_limits.py` reproduces this and references no P&L, so it cannot be overfitted to returns.

## Alpaca infrastructure

**MCP server, filtered.** Alpaca's MCP server exposes 72 tools, including `place_option_order`, `close_all_positions` and `cancel_all_orders` in the same list as its quote endpoints. Handing the model that list would give it a write path that never touches the gate layer, reducing every rule above to decoration. We pass an explicit **allowlist of 19 read-only tools**. It is an allowlist rather than a denylist on purpose: a denylist is correct only until Alpaca ships a tool nobody has heard of, and it fails open on that day. Verified against the live server, not fixtures.

**alpaca-py for gated writes.** `broker.py` is the only file in the repository that can write to Alpaca, and every mutating call runs the gates first. The invariant is checkable by grep.

**Paper behaviours that shaped the design**, all measured on a throwaway dev account rather than inherited:

- Paper fills **market** option orders. A limit priced at the ask, marketable by definition, sat unfilled for 30 seconds. The agent therefore submits market orders, and we say so rather than claiming fills we would not get.
- Paper **does** fill market multi-leg (`OrderClass.MLEG`) orders: a SPY 766/771 vertical filled at $2.90 net debit. The whole design rested on this, so it was worth three throwaway orders to establish rather than assume.
- **Closing a vertical requires the short leg first.** Closing the long leg first leaves the short leg momentarily uncovered and Alpaca rejects it (`40310000`), because level 3 cannot hold a naked short call. This is a correctness constraint on the close path, not a tidiness preference; an agent closing legs in iteration order would throw 403s live.
- A naive nearest-expiry chain query returns SPY dailies and, at the 500-row page cap, never reaches the monthly at all. The expiry gate checks third-Friday alignment, not just distance.
- Alpaca **does** publish live greeks and implied volatility on the chain snapshot. Historical IV is still absent, so nothing greek-based can be backtested; live selection yes, backtest no.

**Two accounts.** Development ran entirely on a throwaway paper account. The competition account is funded to exactly $100,000 and was never traded before kickoff, because the rules require that starting balance and judges read its activity. Account selection is enforced in code with no default, so a forgotten environment variable fails closed rather than silently trading the judged account.

## What is not claimed

No edge. The strategy is a worked example that exercises the machinery. Seven days does not contain a validation cycle, no backtest is possible on Alpaca's options history, and the agent said as much itself in the log: short-leg IV in line with realized, the position resting on a directional read, priced to roughly zero expected value like any fairly-priced option.

The supervised-autonomy design also trades P&L for safety knowingly. The agent runs only in bounded sessions with a human present, nothing is scheduled, and nothing survives the process. That produces a thinner ledger than a scheduled agent would. A seven-day P&L sample is noise either way, and buying a marginally better number by weakening the safety story would be a bad trade.
