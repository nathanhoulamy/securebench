"""Public assertion-free adapter for bounded fixed-record transaction runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any


RUN_SECONDS = 5


def _replace_regular_file(path: Path, content: str) -> None:
    """Replace one file without following a Candidate-created symlink."""

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open(path.parent, directory_flags)
    try:
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        descriptor = os.open(path.name, file_flags, 0o600, dir_fd=parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content.encode("utf-8", errors="strict"))
    finally:
        os.close(parent)


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        process.wait(timeout=1)


def _run_candidate() -> tuple[int, bool]:
    process = subprocess.Popen(
        [sys.executable, "/app/program.py"],
        cwd="/app",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    timed_out = False
    try:
        exit_code = process.wait(timeout=RUN_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        _stop_process_group(process)
        exit_code = 124
    else:
        _stop_process_group(process)
    return exit_code, timed_out


def _candidate_error(code: str, message: str) -> None:
    print(
        json.dumps(
            {
                "format": "securebench.adapter-response/v2",
                "status": "candidate_error",
                "failure": {"code": code, "message": message},
            },
            sort_keys=True,
        )
    )


def main() -> None:
    request: dict[str, Any] = json.load(sys.stdin)
    challenge = request["challenge"]
    _replace_regular_file(
        Path("/app/data/ACCOUNTS.DAT"), challenge["initial_accounts"]
    )
    _replace_regular_file(Path("/app/data/BOOKS.DAT"), challenge["initial_books"])
    _replace_regular_file(
        Path("/app/data/TRANSACTIONS.DAT"), challenge["initial_transactions"]
    )

    exit_codes: list[int] = []
    timed_out = False
    for index, input_record in enumerate(challenge["inputs"]):
        try:
            _replace_regular_file(Path("/app/src/INPUT.DAT"), input_record)
        except OSError:
            if index == 0:
                raise
            _candidate_error(
                "candidate_workspace_modified",
                "Candidate modified a required transaction input path",
            )
            return
        exit_code, invocation_timed_out = _run_candidate()
        exit_codes.append(exit_code)
        timed_out = timed_out or invocation_timed_out
        if exit_code != 0:
            break

    print(
        json.dumps(
            {
                "format": "securebench.adapter-response/v2",
                "status": "observed",
                "observation": {
                    "exit_codes": exit_codes,
                    "timed_out": timed_out,
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
