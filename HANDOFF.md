# HANDOFF

Briefing for whoever (human or Claude) opens this repo cold. Read it fully before writing code.

This repo exists for the **Alpaca AI Trading Agents Hackathon** (lablab.ai, 28 Aug - 4 Sep 2026). It is a throwaway learning project. It is **not** production trading infrastructure, and it must never become entangled with the operator's real one.

## 1. The event

Verified 2026-08-25 from saved copies of the event page, the lablab Rule Book, the Hackathon Guidelines and the Getting Started guide (`refs/*.mhtml`, gitignored). This section is no longer speculative. The only thing still open is whatever the kickoff stream adds on 28 Aug.

| | |
| --- | --- |
| Kickoff | Fri **28 Aug 2026, 23:00 SGT** = 15:00 UTC. Operator is registered. |
| Submission deadline | Fri **4 Sep 2026, 23:00 SGT** = 15:00 UTC. Manual submission up to 6h late only with prior organiser approval. |
| Build window | 7 days |
| Prize pool | $6,000: $2,500 / $1,500 / $1,000, plus 2 x $500 social-engagement prizes (each with a 1-month Algo Trader Plus per member) |
| Track | **"Options Alpha Agents"**, single track |
| Teams | 1-6, solo permitted |

### Mandatory, not thematic

All three are stated as core requirements. Failing any one is not a lost point, it is ineligibility.

1. **Autonomous AI trading agent** built on Alpaca's Trading API.
2. **Alpaca MCP server or CLI** must be used. Either satisfies it.
3. **Options trading. "All strategies must incorporate options trading."** The secondary search quoted in the previous draft of this section was right and the live-page reading was wrong. Options are required.
4. **Brand-new dedicated paper account, funded to exactly $100,000.** "Projects run on an existing or reused account will not be eligible for judging." This independently confirms boundary 2 below, which was previously only the operator's own rule.

### Deliverables

- Public **GitHub repository**.
- **Demo application deployed and reachable at a URL**, on Streamlit, Replit or Vercel. Listed as required for interactive evaluation. This is real scope: the agent needs a hosted front end, not just a repo.
- **Video presentation**, MP4, under 5 minutes and under 300MB. The rubric penalises under 3 minutes and rewards a clear problem/solution/value framing inside 5.
- **Slide presentation**, PDF.
- **Cover image**, PNG or JPG, 16:9.
- Title (max 50 chars), short description (max 255 chars), long description (min 100 words), technology and category tags.
- **One-page write-up** covering AI logic, risk gates, and Alpaca infrastructure implementation.
- **The Alpaca paper account ID**, so judges can pull the trading activity and score P&L.
- Optional: up to 5 links to X or LinkedIn posts tagging @lablabai and @AlpacaHQ.

### Judging

The event page lists: **P&L Performance**, Technology Implementation, Creativity & Originality, Presentation & Execution, and social engagement. No weights are published.

The generic lablab Rule Book carries a different four-part rubric (Presentation, Business value, Application of technology, Originality) with 1-5 descriptors. It is the platform default and appears to predate this event. Where they conflict, the event page is the specific and later statement, but the Rule Book descriptors are still the best available guide to how a lablab judge scores a video and a repo. Worth asking in Discord which applies.

### Two consequences worth absorbing before scoping

**P&L is judged, and it is judged from account activity over the competition week.** This is in direct tension with boundary 4 below (no unattended scheduling). An agent that only trades while the operator is at the keyboard will produce a thin ledger. Do not resolve this by leaving something running unattended. Resolve it by making the agent's runs deliberate, logged and hand-triggered, and by saying plainly in the write-up that supervised execution was a design choice. A seven-day P&L sample is noise regardless, so buying a marginally better number by weakening the safety story is a bad trade.

**The account ID is published to judges, and section 2 assumes anything submitted is public.** Scrub account numbers from the video, the slides, the screenshots and the repo, then hand over the ID through the submission form only.

## 2. Hard boundaries

These are not style preferences. Violating them can damage a live system.

1. **Never touch `C:\projects\alpaca-trader`.** Not a branch of it, not a worktree in it, no imports from it, no shared virtualenv. It is a running production paper system with systemd timers on a Linux VPS, an equity ledger, and git hooks that auto-commit and auto-push anything matching `memory/`, `*.md`, or `live/`. A stray file in that tree syncs to the VPS without confirmation.
2. **Use a brand-new, dedicated Alpaca paper account with its own API keys.** Not the operator's existing paper account. That account carries a real track record in `live/equity.jsonl`, and the operator has a standing rule from prior incident review: keep all options experimentation off the track-record account.
3. **Paper only. No live keys in this repo, ever.** Keys go in a gitignored `.env`, never in a tracked file, never in a commit, never in a demo video frame or a screenshot.
4. **No unattended scheduling.** No cron, no systemd timer, no background loop that survives your session. A hackathon agent left running is how a demo becomes an incident.
5. Assume anything you submit becomes public. Scrub account numbers and keys from logs and recordings before submitting.
6. **Two accounts, and never trade the competition one before kickoff.** The rules require the competition account's starting balance to be **set to $100,000**, and judges pull its activity to score P&L. Any fill before 28 Aug 15:00 UTC leaves it at something other than exactly $100,000 and puts pre-competition trades in the history they read. The same rules say plainly to "use any paper account you like during development", so all probing, smoke-testing and supervised-session practice happens on a **separate throwaway dev account**. `.env` points at the dev account until kickoff, then the competition keys go in. `ALPACA_ACCOUNT_ROLE` must be set explicitly to `dev` or `competition`; the broker refuses to construct without it, and refuses `competition` before kickoff. This boundary exists because on 2026-08-25 a probe that submits three real orders was one command away from running against the competition account, and the plan that scheduled it had not noticed.

## 3. Who you are working with

The operator is not a beginner and does not need trading concepts explained. They run `alpaca-trader`, a Python (uv-managed) execution layer on Alpaca carrying roughly $98k of paper capital across a funded risk-premium sleeve (VOO/GLD/TLT), a crypto trend sleeve, a per-sleeve gross-budget governor with a drawdown brake, immutable execute-run dossiers, and a covered-call overlay whose decision logic is unit-tested across ~190 tests. They have already shipped and paper-validated a live options order path.

Practical implications: skip the tutorials, do not re-derive things they have already measured, and expect them to ask for evidence. Their global conventions (uv, PowerShell, commit format, terse output, no em-dashes) live in `~/.claude/CLAUDE.md` and apply here automatically. Do not restate them in this repo.

## 4. Alpaca options facts already paid for

The single highest-value thing in this handoff. Every line below was learned by running against a live Alpaca paper account in July 2026, mostly the hard way. Re-discovering any of it costs a day you do not have in a 7-day sprint.

- **Alpaca paper fills MARKET option orders only. LIMIT option orders rest unfilled indefinitely, even when marketable at the bid.** This is the one that will silently eat your build. If your agent submits limit orders and nothing fills, the agent is not broken. For a demo you want fills, so use market orders on paper and say so in the writeup.
- ~~**Alpaca provides no options IV, no greeks, no NBBO history.**~~ **Half of this is now stale. Corrected 2026-08-25.** The option chain snapshot endpoint returns **live greeks and implied volatility**: `get_option_chain` came back with `delta=0.8273 gamma=0.0085 rho=0.3966 theta=-0.2212 vega=0.5019` and `implied_volatility=0.1539` on a SPY 18 Sep contract. Delta-targeted strike selection is therefore available live, and the agent read and reasoned from real greeks during its first session rather than inventing them. What remains true: options **history** is still bars and trades from Feb 2024, with no historical IV surface and no NBBO history, so nothing greek-based or IV-based can be **backtested**. Live selection yes, backtest no.

- **A position object carries no open timestamp.** `get_all_positions` returns symbol, signed `qty`, `avg_entry_price`, `current_price` and P&L, and nothing that says when the position was opened. Reconstructing the book at session start therefore stamps `opened_at` with the load time, which over-dedupes for the first 30 minutes rather than under-dedupes. Getting the true fill time means walking order history per leg.
- **`avg_entry_price` is positive on both legs.** The sign lives in `qty` (`'-3'` for a short, as a **string**). So net debit is `long.avg_entry_price - short.avg_entry_price`, matching the ask-minus-bid convention the gates already use. Measured on the live 745/750 spread: `1.93 - 2.62 = -0.69`, exactly the credit it filled at.
- **Snapshot greeks are an object, not a dict.** `snapshot.greeks` is an `alpaca.data.models.snapshots.OptionsGreeks`, so it is `greeks.delta`, not `greeks["delta"]`. Its repr prints like a dict, which is how you get this wrong. Greeks are readable **with the market closed**, which makes book reconstruction possible before the open.
- **Expiry selection is a live footgun.** Naive nearest-expiry logic picks weeklies when you meant the monthly third Friday. Verify which contract you actually selected before submitting anything.
- Short option market value lands in `account.short_market_value`, so naive gross-exposure math over-counts a covered position. Exclude option MV if you display exposure.
- OCC/OSI symbols need real parsing. Do not regex them casually.
- Paper options level 3 was approved and `options_buying_power` was exposed on the operator's account. A fresh account may differ, so check `options_approved_level` early on day one, because approval is a hard prerequisite and may not be instant.
- **XSP and SPX contracts are tradable on Alpaca paper** (confirmed 2026-07-07), European and cash-settled. Older docs claiming "coming soon" are stale.
- Built against `alpaca-py` 0.43.4.
- On 2026-07-07 Alpaca's paper engine had a platform-wide outage that transiently wiped all positions from the account. Support restored it. **If account state goes insane, it is probably Alpaca, not you. Do not trade to "fix" it.**

Added 2026-08-25, measured on a fresh dev paper account (`probe_fills.py --trade`):

- **The market-fills-only rule still holds.** A market single-leg buy filled at $11.00. A limit buy priced at the ask, marketable by definition, sat at `new` for 30 seconds and never filled. Nothing about this changed between July and now, and it is not account-specific.
- **Market multi-leg (`OrderClass.MLEG`) orders DO fill on paper.** A SPY 766/771 call vertical filled at $2.90 net debit. The July notes said nothing about multi-leg, and the entire agent design rests on this, so it was worth the three orders to find out. Verticals are viable; no sequential-leg fallback is needed.
- **Closing a vertical: short leg first, always.** Closing the long leg first leaves the short leg momentarily uncovered, and Alpaca rejects it with `40310000 account not eligible to trade uncovered option contracts`. Level 3 cannot hold a naked short call, so the close order is not cosmetic. Sort positions by quantity ascending and the negatives go first.

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

Items 1-3 were done on 2026-08-25, three days ahead of kickoff.

1. ~~Pull the official rules, deliverables, and judging criteria.~~ **Done.** Section 1 is rewritten from saved copies.
2. ~~Create the dedicated paper account.~~ **Done.** $100,000, `options_approved_level` 3, ACTIVE, keys in gitignored `.env`. Verify with `uv run python check_account.py`.
3. ~~Stand up the Alpaca MCP server.~~ **Done.** `alpaca-mcp-server` 3.4.7, 72 tools, registered at **local** scope, not project scope: project scope writes a tracked `.mcp.json` and would commit the keys. `uv run python mcp_smoke.py` drives it over raw stdio and makes a live read-only call, so it can be re-verified without a session restart.
4. **Open.** Needs market hours. `uv run python probe_fills.py --trade` buys 1 ATM monthly call at market, then submits a marketable limit, polls both and prints whether section 4's market-fills-only claim still holds. Dry-run by default. Until this runs, that claim is inherited, not verified on this account.
5. Only then decide scope. Pick something demoable in five days, not seven. Note that section 1 now adds a hosted demo URL to the deliverables, which is a day of work nobody had budgeted.

## 8. Testing

Non-trivial logic (order sizing, strike selection, any guardrail) leaves one runnable check behind, an `assert`-based self-check or a small `test_*.py`. No frameworks, no fixtures. Guardrails and the paper-only enforcement are the exception to hackathon corner-cutting: test those properly, because they are the thing standing between a demo agent and a bad order.
