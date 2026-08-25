# HANDOFF

Briefing for whoever (human or Claude) opens this repo cold. Read it fully before writing code.

This repo exists for the **Alpaca AI Trading Agents Hackathon** (lablab.ai, 28 Aug - 4 Sep 2026). It is a throwaway learning project. It is **not** production trading infrastructure, and it must never become entangled with the operator's real one.

## 1. The event

Verified from the lablab live dashboard on 2026-08-25:

| | |
| --- | --- |
| Kickoff | Fri **28 Aug 2026, 15:00 UTC**. Registration closes at kickoff. Operator is registered. |
| Submission deadline | Fri **4 Sep 2026, 15:00 UTC** |
| Build window | 7 days |
| Prize pool | $6,000 |
| Track | **"Options Alpha Agents"** (single track, open to all) |
| Format | Fully online, teams of 1-6 |
| Stack | Alpaca Trading API, **Alpaca MCP server**, Alpaca CLI. Paper environment. |

**Unverified, resolve at kickoff.** The lablab page is a JS app and did not expose these to a plain fetch: exact submission deliverables (repo? demo video? length?), judging criteria and weights, whether options usage is strictly mandatory or just the track's theme, prize split, and any rules on pre-existing code. A secondary search suggested options are required and quoted a $5,000 pool, both of which conflict with what the live page actually states. **Do not design around any of it until you have read the official rules.** First action on 28 Aug is to pull the real rules from the event page and the lablab Discord, then write them into this file, replacing this paragraph.

## 2. Hard boundaries

These are not style preferences. Violating them can damage a live system.

1. **Never touch `C:\projects\alpaca-trader`.** Not a branch of it, not a worktree in it, no imports from it, no shared virtualenv. It is a running production paper system with systemd timers on a Linux VPS, an equity ledger, and git hooks that auto-commit and auto-push anything matching `memory/`, `*.md`, or `live/`. A stray file in that tree syncs to the VPS without confirmation.
2. **Use a brand-new, dedicated Alpaca paper account with its own API keys.** Not the operator's existing paper account. That account carries a real track record in `live/equity.jsonl`, and the operator has a standing rule from prior incident review: keep all options experimentation off the track-record account.
3. **Paper only. No live keys in this repo, ever.** Keys go in a gitignored `.env`, never in a tracked file, never in a commit, never in a demo video frame or a screenshot.
4. **No unattended scheduling.** No cron, no systemd timer, no background loop that survives your session. A hackathon agent left running is how a demo becomes an incident.
5. Assume anything you submit becomes public. Scrub account numbers and keys from logs and recordings before submitting.

## 3. Who you are working with

The operator is not a beginner and does not need trading concepts explained. They run `alpaca-trader`, a Python (uv-managed) execution layer on Alpaca carrying roughly $98k of paper capital across a funded risk-premium sleeve (VOO/GLD/TLT), a crypto trend sleeve, a per-sleeve gross-budget governor with a drawdown brake, immutable execute-run dossiers, and a covered-call overlay whose decision logic is unit-tested across ~190 tests. They have already shipped and paper-validated a live options order path.

Practical implications: skip the tutorials, do not re-derive things they have already measured, and expect them to ask for evidence. Their global conventions (uv, PowerShell, commit format, terse output, no em-dashes) live in `~/.claude/CLAUDE.md` and apply here automatically. Do not restate them in this repo.

## 4. Alpaca options facts already paid for

The single highest-value thing in this handoff. Every line below was learned by running against a live Alpaca paper account in July 2026, mostly the hard way. Re-discovering any of it costs a day you do not have in a 7-day sprint.

- **Alpaca paper fills MARKET option orders only. LIMIT option orders rest unfilled indefinitely, even when marketable at the bid.** This is the one that will silently eat your build. If your agent submits limit orders and nothing fills, the agent is not broken. For a demo you want fills, so use market orders on paper and say so in the writeup.
- **Alpaca provides no options IV, no greeks, no NBBO history.** Options data starts Feb 2024 and is bars and trades only. Any "delta-targeted" or "IV-rank" agent cannot be backtested on Alpaca data. Select strikes by **moneyness** instead, and be honest in the demo that it is moneyness.
- **Expiry selection is a live footgun.** Naive nearest-expiry logic picks weeklies when you meant the monthly third Friday. Verify which contract you actually selected before submitting anything.
- Short option market value lands in `account.short_market_value`, so naive gross-exposure math over-counts a covered position. Exclude option MV if you display exposure.
- OCC/OSI symbols need real parsing. Do not regex them casually.
- Paper options level 3 was approved and `options_buying_power` was exposed on the operator's account. A fresh account may differ, so check `options_approved_level` early on day one, because approval is a hard prerequisite and may not be instant.
- **XSP and SPX contracts are tradable on Alpaca paper** (confirmed 2026-07-07), European and cash-settled. Older docs claiming "coming soon" are stale.
- Built against `alpaca-py` 0.43.4.
- On 2026-07-07 Alpaca's paper engine had a platform-wide outage that transiently wiped all positions from the account. Support restored it. **If account state goes insane, it is probably Alpaca, not you. Do not trade to "fix" it.**

## 5. Strategy: do not re-run dead experiments

The operator maintains a kill ledger of roughly 30 adjudicated experiments. Options ideas already rejected on evidence, so do not present them as the hackathon's insight:

iron condors, butterflies and credit spreads (weak risk-adjusted returns, long wings buy back the richest premium); protective puts and long-option gates (negative alpha); the wheel (over 99% of return is the stock leg); weekly tenors (worse than monthly net of premium); GLD covered calls (never overwrite the book's trending asset); 0DTE and weekly selling, dispersion, short-index-vol, crypto basis arb, intraday stat-arb, box-spread financing, merger arb (all rejected on Alpaca/retail constraints).

Two process rules from that ledger that apply directly here: **predictive gating on premia hurts**, and **the fill price is part of the signal** (an edge that only exists at an unfillable price is not an edge).

None of this blocks you. It just means the interesting contribution is **the agent architecture, not the strategy**.

## 6. What to optimize for

The goal is **learning what is possible and what good practice looks like**, explicitly not winning. Optimize accordingly, and note that this inverts the operator's normal discipline:

- **Optimize for a legible demo and novel plumbing.** In `alpaca-trader` nothing gets funded without survivorship-clean data and a bootstrap CI. That bar is correct there and fatal here. Seven days does not contain a validation cycle. Ship the machinery, present the strategy as a worked example, and do not claim an edge you have not measured.
- **Spend the week on genuinely new surface**: the Alpaca MCP server, the Alpaca CLI, agent orchestration and tool-calling, guardrails on an LLM that can place orders, options chain endpoints. The operator's existing system is deterministic and quantitative, so LLM-in-the-loop trading is the actual unexplored territory.
- **Guardrails are the most transferable output.** An agent with authority to trade needs position limits, a kill switch, a dry-run mode, and an audit log of every decision and its inputs. Building that well is the best practice worth carrying home, and it also demos well.
- **Do not port strategy code from `alpaca-trader`.** It is coupled to a governor that will not exist here, and adapting it will cost more than writing something small and purpose-built.

## 7. Day-one checklist

1. Pull the official rules, deliverables, and judging criteria. Rewrite section 1 with them.
2. Create the dedicated paper account. Confirm `options_approved_level` is sufficient. Store keys in gitignored `.env`.
3. Stand up the Alpaca MCP server and confirm a read-only call works end to end.
4. Place one throwaway market option order to confirm the fill behavior in section 4 still holds on the new account.
5. Only then decide scope. Pick something demoable in five days, not seven.

## 8. Testing

Non-trivial logic (order sizing, strike selection, any guardrail) leaves one runnable check behind, an `assert`-based self-check or a small `test_*.py`. No frameworks, no fixtures. Guardrails and the paper-only enforcement are the exception to hackathon corner-cutting: test those properly, because they are the thing standing between a demo agent and a bad order.
