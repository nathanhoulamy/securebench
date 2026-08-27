"""Public assertion-free process adapter for the circuit gate simulator."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


COMPILE_SECONDS = 10
SIMULATION_SECONDS = 15
STDOUT_BYTES = 128
STDERR_BYTES = 1024


def _compile_simulator() -> Path:
    source = Path(__file__).resolve().with_name("simulator.c")
    binary = Path("/app/.securebench-circuit-simulator")
    completed = subprocess.run(
        [
            "gcc",
            "-O3",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=COMPILE_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("immutable circuit simulator failed to compile")
    return binary


def _bounded(value: str, maximum_bytes: int) -> str:
    encoded = value.encode("utf-8", errors="replace")[:maximum_bytes]
    return encoded.decode("utf-8", errors="ignore")


def main() -> None:
    request = json.load(sys.stdin)
    input_value = request["challenge"]["input"]
    simulator = _compile_simulator()
    try:
        completed = subprocess.run(
            [str(simulator), "/app/gates.txt", str(input_value)],
            capture_output=True,
            text=True,
            timeout=SIMULATION_SECONDS,
            check=False,
        )
        exit_code = completed.returncode
        stdout = _bounded(completed.stdout, STDOUT_BYTES)
        stderr = _bounded(completed.stderr, STDERR_BYTES)
    except subprocess.TimeoutExpired:
        exit_code = 124
        stdout = ""
        stderr = "simulation_timeout\n"

    print(json.dumps({
        "format": "securebench.adapter-response/v2",
        "status": "observed",
        "observation": {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        },
    }, sort_keys=True))


if __name__ == "__main__":
    main()
