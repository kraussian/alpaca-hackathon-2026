import argparse
import asyncio
import sys

from dotenv import load_dotenv

from agent_pkg.session import run_session


def main() -> None:
    # The model writes arrows and dashes; the Windows console defaults to
    # cp1252 and raises UnicodeEncodeError mid-session on the first one.
    # Killing a live trading session over a console codec would be absurd.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv(".env")
    ap = argparse.ArgumentParser(prog="agent_pkg")
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--max-orders", type=int, default=3)
    ap.add_argument("--underlyings", nargs="+", default=["SPY", "QQQ", "IWM"])
    args = ap.parse_args()
    asyncio.run(run_session(args.minutes, args.max_orders, args.underlyings))


if __name__ == "__main__":
    main()
