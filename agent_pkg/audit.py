"""Append-only decision log.

Written before the order is submitted, not after the fill. If the submission
throws, the reasoning that led to it is what you need, and a log written
afterwards would not have it.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

_ACCOUNT = re.compile(r"\bPA[A-Z0-9]{8,}\b")
_KEY = re.compile(r"\bPK[A-Z0-9]{16,}\b")


def scrub(text: str) -> str:
    """Remove account numbers and API keys.

    Runs at write time, not before submission. The submission rules assume
    anything submitted is public, and this log ships in a public repository to
    feed the dashboard, so there is no later moment at which scrubbing would
    still be a choice.
    """
    return _ACCOUNT.sub("<account>", _KEY.sub("<key>", text))


class AuditLog:
    def __init__(self, session_id: str, directory: Path = Path("logs")) -> None:
        self.session_id = session_id
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / f"session-{session_id}.jsonl"

    def write(self, event: str, **fields: object) -> dict:
        record = {
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            "session_id": self.session_id,
            "event": event,
            **fields,
        }
        line = scrub(json.dumps(record, default=str))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return json.loads(line)
