# Runbook

The operating document for competition week. Everything still load-bearing from `HANDOFF.md` lives here now; that file was a pre-kickoff briefing and has been removed.

`.env` is on `ALPACA_ACCOUNT_ROLE=competition`. Every session from here counts for judging.

## The week

Submission closes **Fri 4 Sep 2026, 15:00 UTC / 23:00 SGT**. Late submission needs prior organiser approval, so treat it as a hard stop.

| Session | Market open (UTC / SGT) | Notes |
| --- | --- | --- |
| Mon 31 Aug | 13:30 / 21:30 | First competition session. Book is empty, so aggregate gates cannot veto anything yet. |
| Tue 1 Sep | 13:30 / 21:30 | First session where the loaded book can veto. Watch that it loads. |
| Wed 2 Sep | 13:30 / 21:30 | |
| Thu 3 Sep | 13:30 / 21:30 | Last full session. Record the demo video after this one. |
| Fri 4 Sep | 13:30 / 21:30 | Market opens 90 minutes before the deadline. Do not plan to trade here. Submit instead. |

The market closes at 20:00 UTC / 04:00 SGT. A session started at the open has six and a half hours of window; you will not use it.

## Before every session

```powershell
uv run python preflight.py
```

Expect: role `competition`, account ACTIVE, options level 3, market OPEN, kill switch clear. It reads the account through the same fail-closed credential path the session uses and cannot write anything.

Then confirm the working tree is clean and the suite is green, because the session appends to `logs/` and you want that diff to be the only one:

```powershell
git status --short
uv run pytest -q
```

## Running a session

```powershell
uv run python -m agent_pkg --minutes 30 --max-orders 1 --underlyings SPY QQQ IWM
```

Defaults are 60 minutes and 3 orders. Both stop conditions are independent: whichever trips first ends the session.

**Watch it.** That is the whole design. Nothing is scheduled, nothing survives the process, and a session with nobody in front of it is the thing this project exists to argue against.

Watching is only possible because `__main__.py` sets `line_buffering` on stdout. Without it a session redirected to a file or piped to another process is block buffered, and the first thing you see is the whole transcript arriving at once after the process has already exited. That happened on Mon 31 Aug: the session looked hung for four minutes and had in fact already finished. If output ever goes silent again while the process is alive, suspect buffering before suspecting the agent.

What to look for, in order:

1. The startup banner naming the role. If it says `dev`, stop; the session will not count.
2. The book loading from the account. From Tuesday on this should list yesterday's positions. An empty book on day three means `positions.py` is not seeing the account and the aggregate gates are blind again.
3. Gate verdicts printing for each proposal, pass or veto.
4. The fill, or a stated decline. **A session that declines to trade is a good session.** The model is told it is not scored on trade count, and a declined trade with reasoning in the log is better evidence than a marginal one.

### Aborting

From another terminal, in the repo root:

```powershell
echo stop > .kill
```

Checked before every write. It stops the next order, not the process; close the terminal too if you want the session gone. Delete `.kill` before the next session, and `preflight.py` will tell you if you forgot.

## After every session

**The deployed dashboard reads `logs/session-*.jsonl` out of the repository.** A session that is not committed and pushed is invisible to judges. This is the single most missable step in the week.

```powershell
git status --short           # expect exactly one new logs/session-*.jsonl
git add logs/
git commit -m "Record the <day> competition session"
git push
```

Then open the deployed dashboard and confirm the new session appears in the picker.

Before pushing, glance at the log for anything that should not be public. Account numbers are not written to it by design, but this is the last cheap moment to check.

## If something goes wrong

**Positions vanish, or account state is nonsense.** It is probably Alpaca, not you. Their paper engine wiped all positions platform-wide on 2026-07-07 and support restored them. **Do not trade to "fix" it.** Stop the session, screenshot the state, wait.

**An order is rejected with `40310000 account not eligible to trade uncovered option contracts`.** A close ran the long leg before the short. The close path sorts by quantity ascending so negatives go first; if this appears, that ordering broke.

**The session refuses to start because a leg's delta cannot be read.** Working as intended. A session blind to its own directional exposure should not open positions. Retry once; if the chain snapshot is still returning no greeks, skip the day and say so in the log.

**A gate vetoes repeatedly and you are tempted to raise a limit.** Do not, not this week. The limits are derived from a stated drawdown tolerance and their sensitivity is measured in `calibrate_limits.py`. Raising one mid-competition to get a fill converts the whole submission from "these are backstops" into "these are whatever let the trade through", and that is the argument the project is making.

## Submission day, Fri 4 Sep

Work backwards from 15:00 UTC / 23:00 SGT. Do not trade this morning.

1. **By Thu evening**: record the video (`docs/video-script.md`), against a dashboard showing real competition fills.
2. **T-4h**: final `uv run pytest -q` and `uv run ruff check .`, push everything, confirm the repo is public in a logged-out browser window.
3. **T-3h**: open the deployed dashboard in a private window. No session cookie, no cached login. If it does not load there, it does not load for a judge.
4. **T-2h**: fill the form from `docs/submission.md`. The account ID goes in the form field and nowhere else.
5. **T-1h**: last read of the pre-submit checklist at the bottom of `docs/submission.md`.

## Hard boundaries

Carried forward from the pre-kickoff briefing. These are not style preferences.

1. **Never touch `C:\projects\alpaca-trader`.** Not a branch, not a worktree, no imports, no shared virtualenv. It is a running production paper system with VPS timers and git hooks that auto-commit and auto-push anything matching `memory/`, `*.md` or `live/`. A stray file in that tree syncs without confirmation.
2. **Paper only, and no live keys in this repository, ever.** Keys live in a gitignored `.env`. Never in a tracked file, a commit, a screenshot, or a video frame.
3. **Nothing scheduled.** No cron, no timer, no background loop that survives the session. A hackathon agent left running is how a demo becomes an incident.
4. **Assume everything submitted is public.** The account ID goes to judges through the form; scrub it from everything else.
5. **The dev account stays available.** `ALPACA_ACCOUNT_ROLE=dev` still works and still points at the throwaway account. Any experiment, probe or rehearsal runs there, not on the judged account.

## Appendix: Alpaca facts already paid for

Learned by running against live paper accounts, mostly the hard way. The ones that shaped the design are in `docs/writeup.md`; these are the rest, kept because rediscovering any of them costs a day.

- **Paper fills market option orders only.** A limit priced at the ask, marketable by definition, rests unfilled indefinitely. If nothing fills, the agent is not broken.
- **Market multi-leg (`OrderClass.MLEG`) orders do fill.**
- **A position object carries no open timestamp.** `get_all_positions` returns no field saying when a position was opened, so reconstructing the book stamps `opened_at` with load time. That over-dedupes for the first 30 minutes rather than under-dedupes, which is the safe direction. True fill times mean walking order history per leg.
- **`avg_entry_price` is positive on both legs.** The sign lives in `qty`, and `qty` is a **string** (`'-3'` for a short). Net debit is `long.avg_entry_price - short.avg_entry_price`.
- **Snapshot greeks are an object, not a dict.** `snapshot.greeks.delta`, not `snapshot.greeks["delta"]`. The repr prints like a dict, which is how you get this wrong. Greeks are readable with the market closed, which is what makes pre-open book reconstruction possible.
- **Short option market value lands in `account.short_market_value`**, so naive gross-exposure math over-counts a covered position.
- **OCC/OSI symbols need real parsing.** Do not regex them casually.
- **XSP and SPX are tradable on Alpaca paper**, European and cash-settled. Docs claiming otherwise are stale.
- **Live greeks and IV are on the chain snapshot; historical IV is not.** Live selection yes, backtest no.
- Built against `alpaca-py` 0.43.4.
- Model ID is exactly `claude-opus-5`, no date suffix. Do not pass `budget_tokens`, `temperature`, `top_p` or `top_k` to it; all four return HTTP 400.
