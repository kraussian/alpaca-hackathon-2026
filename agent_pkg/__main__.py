import argparse
import asyncio
import sys

from dotenv import load_dotenv

from agent_pkg.session import run_session


def main() -> None:
    # The model writes arrows and dashes; the Windows console defaults to
    # cp1252 and raises UnicodeEncodeError mid-session on the first one.
    # Killing a live trading session over a console codec would be absurd.
    # line_buffering because stdout redirected to a file or a pipe is block
    # buffered by default: nothing surfaces until the process exits, and a
    # session you cannot watch in flight is one you cannot abort in flight.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(
                encoding="utf-8", errors="replace", line_buffering=True
            )

    load_dotenv(".env")
    ap = argparse.ArgumentParser(prog="agent_pkg")
    # The competition session's values, not the permissive ones: an
    # invocation that forgets the flags should get the smaller session,
    # not a longer one with a higher order cap.
    ap.add_argument("--minutes", type=int, default=30)
    ap.add_argument("--max-orders", type=int, default=1)
    ap.add_argument("--underlyings", nargs="+", default=["SPY", "QQQ", "IWM"])
    # Lets a session be rehearsed against a specific path (closing, puts,
    # debit spreads) without waiting for a market-hours window.
    ap.add_argument("--task", default=None)
    args = ap.parse_args()
    asyncio.run(run_session(args.minutes, args.max_orders, args.underlyings, args.task))


if __name__ == "__main__":
    main()
