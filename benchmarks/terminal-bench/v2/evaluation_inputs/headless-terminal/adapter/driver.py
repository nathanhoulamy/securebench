"""Untrusted child that invokes the Candidate terminal interface."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time


DEPENDENCIES = Path("/app/headless_terminal_dependencies")


def main() -> None:
    request = json.loads(sys.stdin.readline())
    steps = request["steps"]
    ready_fd = int(os.environ["SECUREBENCH_READY_FD"])
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

    # Signal readiness on a dedicated descriptor the Candidate cannot reach
    # through its own stdout, then keep this process -- and whatever it holds
    # open, such as a pty session or a background job started through it --
    # alive until the public Adapter has finished observing bounded evidence.
    # This matches upstream, where the file/HTTP checks run while the Python
    # process that constructed the terminal object is still alive.
    os.write(ready_fd, b"1")
    os.close(ready_fd)
    sys.stdin.readline()


if __name__ == "__main__":
    main()
