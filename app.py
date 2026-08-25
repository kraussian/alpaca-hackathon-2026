"""Public dashboard over the agent's audit log.

Deliberately read-only and credential-free. Nothing reachable from the public
internet can place an order; the interactivity is replay, not authority. See
the design spec, section 8.

Every number on this page comes from a committed JSONL log written before the
corresponding order was submitted. Nothing here is recomputed or inferred.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

LOGS = Path("logs")

st.set_page_config(page_title="Options Alpha Agent", page_icon="🛡️", layout="wide")


@st.cache_data
def load(path: str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:,.2f}"


st.title("Options Alpha Agent")
st.caption(
    "An LLM picks defined-risk option verticals. A deterministic gate layer sits "
    "between its tool call and the broker and can veto any of them. This page "
    "replays what happened, vetoes included."
)

files = sorted(LOGS.glob("session-*.jsonl"), reverse=True)
if not files:
    st.warning("No session logs found in `logs/`.")
    st.stop()


def label(p: Path) -> str:
    rows = load(str(p))
    orders = sum(1 for r in rows if r["event"] == "submission")
    vetoes = sum(
        1 for r in rows if r["event"] == "gate_verdict" and not r.get("allowed")
    )
    return f"{p.stem.replace('session-', '')}  ({orders} orders, {vetoes} vetoes)"


choice = st.sidebar.selectbox("Session", files, format_func=label)
records = load(str(choice))

start = next((r for r in records if r["event"] == "session_start"), {})
end = next((r for r in records if r["event"] == "session_end"), {})
mcp = next((r for r in records if r["event"] == "mcp_tools"), {})

with st.sidebar:
    st.subheader("Session")
    st.write(f"**Account role:** `{start.get('role', 'unknown')}`")
    st.write(f"**Underlyings:** {', '.join(start.get('underlyings', []))}")
    st.write(f"**Order cap:** {start.get('max_orders', 'n/a')}")
    st.write(f"**Wall clock:** {start.get('minutes', 'n/a')} min")
    if mcp:
        st.write(
            f"**MCP tools:** {len(mcp.get('allowed', []))} allowed of "
            f"{mcp.get('exposed', '?')} exposed"
        )
        with st.expander("Read-only allowlist"):
            st.write("\n".join(f"- `{t}`" for t in mcp.get("allowed", [])))
        st.caption(
            "Alpaca's MCP server also exposes order placement, position closing "
            "and order cancellation. Those are filtered out, so the model's only "
            "write path is the gated one."
        )
    if start.get("limits"):
        with st.expander("Risk limits in force"):
            st.json(start["limits"])

st.divider()

step = st.slider("Replay to event", 1, len(records), len(records))
shown = records[:step]

vetoes = [r for r in shown if r["event"] == "gate_verdict" and not r.get("allowed")]
allowed = [r for r in shown if r["event"] == "gate_verdict" and r.get("allowed")]
submits = [r for r in shown if r["event"] == "submission" and r.get("order_id")]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Events replayed", f"{len(shown)} / {len(records)}")
c2.metric("Orders submitted", len(submits))
c3.metric("Gate vetoes", len(vetoes))

e0, e1 = start.get("equity"), end.get("equity")
if e0 is not None and e1 is not None:
    c4.metric("Session P&L", money(e1 - e0), delta=f"{(e1 - e0) / e0 * 100:+.3f}%")
else:
    c4.metric("Session P&L", "n/a")

if vetoes:
    st.subheader("What the gates stopped")
    for v in vetoes:
        o = v.get("order")
        head = (
            f"{o['underlying']} {o['expiry']} {o['option_type']} "
            f"{o['long_strike']:g}/{o['short_strike']:g} x{o['qty']}"
            if o
            else "close request"
        )
        st.error(f"**{head}** — " + " / ".join(v.get("reasons", [])))
else:
    st.info("No gate vetoes in the replayed range.")

st.divider()
st.subheader("Decision trail")

ICON = {
    "session_start": "▶️",
    "mcp_tools": "🔌",
    "decision": "💭",
    "tool_call": "🔧",
    "gate_verdict": "🛡️",
    "submission": "✅",
    "kill_switch": "🛑",
    "session_stop": "⏹️",
    "session_end": "⏹️",
}

for r in shown:
    ev = r["event"]
    ts = r["timestamp"][11:19]
    if ev == "decision":
        st.markdown(f"{ICON[ev]} `{ts}`")
        st.markdown(r["reasoning"])
    elif ev == "tool_call":
        st.markdown(
            f"{ICON[ev]} `{ts}` **{r['tool']}**"
            + ("  ← gated write" if r["tool"].endswith("vertical") else "")
        )
        st.code(json.dumps(r["input"], indent=2), language="json")
    elif ev == "gate_verdict":
        if r.get("allowed"):
            st.success(f"{ICON[ev]} `{ts}` gates: **allowed**")
        else:
            st.error(
                f"{ICON[ev]} `{ts}` gates: **vetoed** — "
                + " / ".join(r.get("reasons", []))
            )
    elif ev == "submission":
        if r.get("order_id"):
            st.info(f"{ICON[ev]} `{ts}` submitted to Alpaca — order `{r['order_id']}`")
        else:
            st.info(f"{ICON[ev]} `{ts}` closed {r.get('short')} then {r.get('long')}")
    elif ev == "kill_switch":
        st.warning(f"{ICON[ev]} `{ts}` kill switch engaged — {r.get('reason', '')}")
    elif ev in ICON:
        detail = ""
        if ev == "session_start":
            detail = f" — role `{r.get('role')}`, equity {money(r.get('equity'))}"
        elif ev == "session_end":
            detail = (
                f" — {r.get('orders_placed', 0)} order(s), "
                f"equity {money(r.get('equity'))}"
            )
        elif ev == "mcp_tools":
            detail = (
                f" — {len(r.get('allowed', []))} of {r.get('exposed')} tools allowed"
            )
        st.caption(f"{ICON[ev]} `{ts}` {ev.replace('_', ' ')}{detail}")

st.divider()
st.caption(
    "Paper trading only. This page holds no credentials and cannot place, modify "
    "or cancel an order."
)
