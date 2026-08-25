import argparse
import asyncio

from dotenv import load_dotenv

from agent_pkg.session import run_session


def main() -> None:
    load_dotenv(".env")
    ap = argparse.ArgumentParser(prog="agent_pkg")
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--max-orders", type=int, default=3)
    ap.add_argument("--underlyings", nargs="+", default=["SPY", "QQQ", "IWM"])
    args = ap.parse_args()
    asyncio.run(run_session(args.minutes, args.max_orders, args.underlyings))


if __name__ == "__main__":
    main()
