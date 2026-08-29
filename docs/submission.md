# Submission copy

Paste-ready fields for the lablab form. Character counts are of the text between the fences.

## Title (max 50)

```
Options Alpha Agent
```

19 characters.

Alternates, if a longer title reads better on the gallery card:

```
Options Alpha Agent: the veto is final
```

38 characters.

## Short description (max 255)

```
An LLM chooses defined-risk option verticals on Alpaca. A deterministic gate layer sits between its tool call and the broker and can veto any of them. 16 gates, 105 tests, every decision and veto in an append-only audit log a public dashboard replays.
```

251 characters.

## Long description (min 100 words)

```
An LLM with order authority is a new kind of risk: Alpaca's MCP server exposes 72 tools, and place_option_order sits in the same list as the quote endpoints. Hand a model that list and every risk rule you write becomes decoration, because there is a write path that never touches it.

Options Alpha Agent puts the authority somewhere the model cannot reach. Claude Opus 5 reads the account, the underlying and the monthly option chain through an allowlist of 19 read-only MCP tools, then proposes a defined-risk vertical on SPY, QQQ or IWM, selecting strikes by delta rather than moneyness. Between that proposal and Alpaca sits gates.py: pure functions, no network, no account object, no model, sixteen rules covering paper-only enforcement, account role, structure, third-Friday expiry, quote sanity, per-position and book-level loss caps, short delta, book net delta, dedupe and a kill switch. broker.py is the only file in the repository that can write to Alpaca, and every mutating call runs the gates first. The invariant is checkable by grep.

The gates are not decorative. One vetoed a real order: the model proposed 4 lots of a 10-wide QQQ spread risking $3,496, sized to a 3.5%-of-equity heuristic it invented, and restructured to 3 lots at $1,308 once the veto reason came back. Its own words in the log: "the gate was right and I was wrong." Another closed the last unchecked input, the underlying price the model supplied, which multiplied straight into the book delta cap; the broker now reads the quote midpoint itself.

Limits are derived, not tuned. Aggregate loss follows from a 15% drawdown tolerance, per-position from wanting ten concurrent slots, and calibrate_limits.py measures their sensitivity against 6,375 real verticals while referencing no P&L, so it cannot be overfitted to returns. No edge is claimed. Seven days does not contain a validation cycle, Alpaca publishes no historical IV to backtest against, and the agent said as much itself in the log. The contribution is the gate layer, not the strategy.
```

332 words.

## Technology tags

```
Alpaca Trading API, Alpaca MCP Server, Model Context Protocol, Claude Opus 5, Anthropic API, Python, Streamlit, alpaca-py, Options Trading
```

## Category tags

```
Trading Agents, Options, AI Safety, Guardrails, Risk Management, Autonomous Agents, FinTech
```

## Links

| Field | Value |
| --- | --- |
| GitHub repository | https://github.com/kraussian/alpaca-hackathon-2026 |
| Demo application | https://alpaca-hackathon-2026-havyxbrvtlr4axngfxzdjg.streamlit.app/ |
| Write-up | `docs/writeup.md` in the repository |
| Slides | `docs/slides.pdf` |
| Cover image | `docs/cover.png` (1920x1080, 16:9) |
| Video | `docs/demo.mp4` (record last, once the ledger has real fills) |
| Alpaca paper account ID | **Form field only.** Never on screen, never in the repo. |

## Pre-submit checklist

- [ ] Account ID entered in the form and nowhere else.
- [ ] No account number, key, or `.env` contents visible in any video frame, screenshot, or slide.
- [ ] Demo URL loads in a private window (no session cookie, no cached login).
- [ ] Repository is public and `master` is pushed.
- [ ] `uv run pytest -q` and `uv run ruff check .` both clean at the submitted commit.
- [ ] Video is MP4, between 3 and 5 minutes, under 300MB.
- [ ] Cover image is 16:9 PNG or JPG.
