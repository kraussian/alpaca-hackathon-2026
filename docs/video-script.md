# Demo video script

Target 4:10. The rubric penalises under 3:00 and caps at 5:00, so there is room to lose 30 seconds to a slow take without going short. MP4, under 300MB.

**Record this after at least one competition-account session has filled**, so the dashboard on screen shows a real ledger rather than dev-account logs.

## Before you hit record

- [ ] Close every window holding an account number, an API key, or `.env`. The dashboard shows none, but a stray terminal scrollback does.
- [ ] `uv run streamlit run app.py` locally, or open the deployed URL. Deployed is better: it proves the deliverable works.
- [ ] Have the audit log for the vetoed order open and scrolled to the veto.
- [ ] Terminal ready with the session command, cleared of history.
- [ ] Slides open at `docs/slides.pdf` in presenter-free full screen.

## Shot list and narration

### 0:00-0:30 — the problem (slide 2)

> Alpaca's MCP server exposes seventy-two tools. `place_option_order` sits in the same list as the quote endpoints. So if you hand a language model that list, every risk rule you write is decoration, because there is a write path that never touches it.
>
> That is the problem this project is about. Not whether an LLM has a good opinion about SPY. Whether an agent with order authority can be given that authority safely.

Screen: slide 2. Do not read the bullets aloud; they are on screen.

### 0:30-1:05 — the architecture (slide 3)

> The model reads through an allowlist of nineteen read-only MCP tools, out of the seventy-two. An allowlist rather than a denylist, because a denylist is correct right up until Alpaca ships a tool nobody has heard of, and it fails open that day.
>
> It proposes a defined-risk vertical. Between the proposal and Alpaca sits `gates.py`: pure functions, no network, no account object, no model. And `broker.py` is the only file in the repository that can write to Alpaca. That invariant is checkable by grep, which is the point: you can verify it without trusting me.

Screen: slide 3, then cut to the editor for four seconds on the `broker.py` gate call, and four seconds on the allowlist in `mcp_tools.py`.

### 1:05-1:55 — the gate that fired (slide 5, then the log)

> Sixteen gates. Rather than read them out, here is one doing its job.
>
> The model proposed four lots of a ten-wide QQQ call spread. Well argued, correctly priced, and risking three thousand four hundred and ninety-six dollars against a fifteen hundred dollar per-position cap. It had sized to a three-and-a-half-percent-of-equity rule it invented on the spot, rather than the book's rule.
>
> The gate vetoed it and handed the reason back. The model restructured to three lots of a five-wide, thirteen hundred and eight dollars, and that passed. Its own words in the log: "the gate was right and I was wrong."
>
> That is the whole argument in one trade. The dangerous failure was not a bad opinion. It was a fluent, confident, well-reasoned order at twice the size the book allows, with nothing in the reasoning flagging it.

Screen: slide 5, then cut to the dashboard's decision view showing the veto record and the restructured order.

### 1:55-2:35 — the two fixes that came from watching it (slides 6 and 7)

> Two things we only found by running it.
>
> First, the underlying price. It multiplied straight into the book delta cap, and it was arriving from the model with nothing checking it. A wrong ticker or a stale print moves the number the cap is measured against, silently. Interestingly the agent got this right on its own: offered a QQQ print of 717.80 from forty shares pre-market, it refused it and passed the quote midpoint, 712.39. The broker now computes that midpoint itself, so no session has to be that careful again.
>
> Second, the aggregate gates could not see the account. They summed a list that only held orders from the current process, so every session started believing the book was empty. `positions.py` now rebuilds the book from what the account actually holds, and it is verified with a negative control: an order that passes against an empty book, and is vetoed once the real position is loaded.

Screen: slides 6 and 7.

### 2:35-3:20 — live session

> Here it is running.

Screen: run the session live, or a pre-recorded take of it. Show, in this order: the session start banner with the account role, the model reading the chain, the proposal, the gate verdicts printing, and the fill. Narrate only what is not obvious on screen:

> Two independent stop conditions, wall clock and order count. A kill switch in a sentinel file, checked before every write, so it can be tripped from another terminal without finding the process. Nothing is scheduled and nothing survives this process.

If the session declines to trade, keep it. Declining with a stated reason is a valid outcome and the log records why.

### 3:20-3:50 — what is not claimed (slide 10)

> No edge is claimed. The strategy is a worked example that exercises the machinery. Seven days does not contain a validation cycle, and Alpaca publishes no historical implied volatility, so nothing greek-based can be backtested at all.
>
> Supervised autonomy also costs P&L, knowingly. Bounded sessions with a human present produce a thinner ledger than a scheduled agent would. A seven-day sample is noise either way, and buying a slightly better number by weakening the safety story would be a bad trade.

Screen: slide 10.

### 3:50-4:10 — close

> The contribution is the gate layer, not the strategy. The repository is public, the dashboard is live and read-only, and every decision, veto and fill in this video is in the audit log it replays.

Screen: the deployed dashboard URL, on screen long enough to read.

## Notes

- Do not say the account number aloud, and do not show it. It goes in the submission form only.
- The three numbers worth saying slowly are $3,496, $1,500 and $1,308. Everything else can be on screen only.
- If you overrun, cut the second half of the 1:55 section (the `positions.py` bug). It is the best engineering story but the least legible in thirty seconds.
