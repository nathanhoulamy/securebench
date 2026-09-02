"""Untrusted child that invokes the Candidate terminal interface."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time


DEPENDENCIES = Path("/app/headless_terminal_dependencies")


def main() -> None:
    request = json.load(sys.stdin)
    steps = request["steps"]
    sys.path.insert(0, str(DEPENDENCIES))
    sys.path.insert(0, "/app")

    from headless_terminal import HeadlessTerminal

    terminal = HeadlessTerminal()
    for step in steps:
        terminal.send_keystrokes(
            step["keys"],
            wait_sec=step["wait_ms"] / 1000,
        )
    time.sleep(0.05)


if __name__ == "__main__":
    main()
