"""Drive the Alpaca MCP server over stdio and make one read-only call.

Verifies the server end to end without restarting the Claude Code session.
Credentials come from .env and are never printed.
"""

import json
import os
import subprocess
import sys

from dotenv import dotenv_values


def rpc(proc, method, params=None, mid=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if mid is not None:
        msg["id"] = mid
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if mid is None:
        return None
    for line in proc.stdout:
        try:
            got = json.loads(line)
        except json.JSONDecodeError:
            continue
        if got.get("id") == mid:
            return got
    raise RuntimeError(f"no response to {method}")


def main() -> int:
    env = {**os.environ, "ALPACA_PAPER_TRADE": "true", **dotenv_values(".env")}
    assert env["ALPACA_PAPER_TRADE"] == "true", "refusing to run against live"

    proc = subprocess.Popen(
        ["uvx", "alpaca-mcp-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    try:
        init = rpc(
            proc,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
            1,
        )
        print("server:", init["result"]["serverInfo"])
        rpc(proc, "notifications/initialized")

        tools = [t["name"] for t in rpc(proc, "tools/list", {}, 2)["result"]["tools"]]
        print(f"tools: {len(tools)}")

        name = next((t for t in tools if "account" in t), None)
        assert name, f"no account tool among {tools}"
        out = rpc(proc, "tools/call", {"name": name, "arguments": {}}, 3)
        text = out["result"]["content"][0]["text"]
        print(f"--- {name} ---")
        print(text[:600])
        return 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
