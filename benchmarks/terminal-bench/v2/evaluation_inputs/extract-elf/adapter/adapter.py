"""Public assertion-free adapter for one bounded ELF extraction run."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from typing import Any


CASE_PATH = Path("/app/.securebench-case.elf")
MAX_ELF_BYTES = 65_536
MAX_STDOUT_BYTES = 65_536
MAX_STDERR_BYTES = 4_096
RUN_SECONDS = 10


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


def _decode_challenge(challenge: dict[str, Any]) -> bytes:
    encoded = challenge["elf_base64"]
    expected_digest = challenge["elf_sha256"]
    if not isinstance(encoded, str) or not isinstance(expected_digest, str):
        raise ValueError("invalid challenge fields")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("invalid challenge encoding") from error
    if len(content) > MAX_ELF_BYTES:
        raise ValueError("ELF challenge exceeds adapter limit")
    actual_digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if not hmac.compare_digest(actual_digest, expected_digest):
        raise ValueError("ELF challenge digest mismatch")
    return content


def _write_case(content: bytes) -> None:
    directory = os.open(CASE_PATH.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(
            CASE_PATH.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
    finally:
        os.close(directory)


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def _read_available(
    selector: selectors.BaseSelector,
    buffers: dict[str, bytearray],
    limits: dict[str, int],
    timeout: float,
) -> bool:
    exceeded = False
    for key, _ in selector.select(timeout):
        label = str(key.data)
        while True:
            try:
                chunk = os.read(key.fd, 8_192)
            except BlockingIOError:
                break
            if not chunk:
                selector.unregister(key.fileobj)
                break
            remaining = limits[label] - len(buffers[label])
            buffers[label].extend(chunk[: max(0, remaining) + 1])
            if len(buffers[label]) > limits[label]:
                exceeded = True
                break
            if len(chunk) < 8_192:
                break
    return exceeded


def _run_candidate() -> tuple[str, int | None, bytes, bytes]:
    process = subprocess.Popen(
        ["node", "/app/extract.js", str(CASE_PATH)],
        cwd="/app",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("candidate output pipes were not created")
    selector = selectors.DefaultSelector()
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": MAX_STDOUT_BYTES, "stderr": MAX_STDERR_BYTES}
    for label, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, label)

    deadline = time.monotonic() + RUN_SECONDS
    status = "observed"
    exit_code: int | None = None
    try:
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = "timeout"
                break
            if _read_available(selector, buffers, limits, min(0.1, remaining)):
                status = "too_large"
                break
        if status == "observed":
            exit_code = process.poll()
            if exit_code is None:
                raise RuntimeError("candidate process did not report an exit status")
        _stop_process_group(process)

        drain_deadline = time.monotonic() + 0.5
        while selector.get_map() and time.monotonic() < drain_deadline:
            if _read_available(selector, buffers, limits, 0.05):
                status = "too_large"
                break
    finally:
        _stop_process_group(process)
        selector.close()
        process.stdout.close()
        process.stderr.close()
    return status, exit_code, bytes(buffers["stdout"]), bytes(buffers["stderr"])


def main() -> None:
    request: dict[str, Any] = json.load(sys.stdin)
    challenge = request["challenge"]
    if not isinstance(challenge, dict):
        raise ValueError("challenge must be an object")
    _write_case(_decode_challenge(challenge))

    status, exit_code, stdout_bytes, stderr_bytes = _run_candidate()
    if status == "timeout":
        _candidate_error("candidate_timeout", "Candidate extractor exceeded its time limit")
        return
    if status == "too_large":
        _candidate_error(
            "candidate_output_too_large",
            "Candidate extractor exceeded a bounded output limit",
        )
        return
    try:
        stdout = stdout_bytes.decode("utf-8", errors="strict")
        stderr = stderr_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _candidate_error(
            "candidate_output_invalid_utf8",
            "Candidate extractor returned non-UTF-8 output",
        )
        return

    print(
        json.dumps(
            {
                "format": "securebench.adapter-response/v2",
                "status": "observed",
                "observation": {
                    "exit_code": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
