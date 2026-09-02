"""Public assertion-free runner for the Candidate sentiment service."""

from __future__ import annotations

import base64
import binascii
import http.client
import json
import os
from pathlib import Path
import resource
import signal
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any


APP = Path("/app/app.py")
DEPENDENCIES = Path("/app/hf_service_dependencies")
PORT = 5_000
STARTUP_SECONDS = 25
REQUEST_SECONDS = 10
MAX_REQUEST_BYTES = 3_072
MAX_BODY_BYTES = 16_384
MAX_STREAM_BYTES = 32_768


def _decode(value: Any) -> bytes:
    if not isinstance(value, str):
        raise ValueError("request body must be encoded text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("request body is not valid base64") from error
    if len(decoded) > MAX_REQUEST_BYTES:
        raise ValueError("request body exceeds limit")
    return decoded


def _requests(challenge: Any) -> list[bytes]:
    if not isinstance(challenge, dict):
        raise ValueError("challenge must be an object")
    raw_requests = challenge.get("requests")
    if not isinstance(raw_requests, list) or not 1 <= len(raw_requests) <= 8:
        raise ValueError("challenge must contain bounded requests")
    bodies: list[bytes] = []
    for item in raw_requests:
        if not isinstance(item, dict) or set(item) != {"body_base64"}:
            raise ValueError("request must contain exactly one body")
        bodies.append(_decode(item["body_base64"]))
    return bodies


def _child_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (MAX_STREAM_BYTES + 1, MAX_STREAM_BYTES + 1),
    )


def _start_service(
    stdout: Any,
    stderr: Any,
) -> subprocess.Popen[bytes]:
    environment = os.environ.copy()
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(DEPENDENCIES),
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    return subprocess.Popen(
        [sys.executable, str(APP)],
        cwd="/app",
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
        preexec_fn=_child_limits,
    )


def _port_ready(process: subprocess.Popen[bytes]) -> bool:
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _listen_ipv4() -> list[str]:
    addresses: set[str] = set()
    try:
        lines = Path("/proc/net/tcp").read_text(encoding="ascii").splitlines()[1:]
    except (OSError, UnicodeError):
        return []
    for line in lines:
        fields = line.split()
        if len(fields) < 4 or fields[3] != "0A":
            continue
        try:
            address_hex, port_hex = fields[1].split(":", 1)
            if int(port_hex, 16) != PORT or len(address_hex) != 8:
                continue
            address = socket.inet_ntoa(bytes.fromhex(address_hex)[::-1])
        except (OSError, ValueError):
            continue
        addresses.add(address)
    return sorted(addresses)[:8]


def _request(body: bytes) -> dict[str, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=REQUEST_SECONDS)
    try:
        connection.request(
            "POST",
            "/sentiment",
            body=body,
            headers={"Content-Type": "application/json", "Connection": "close"},
        )
        response = connection.getresponse()
        content = response.read(MAX_BODY_BYTES + 1)
        return {
            "status": int(response.status),
            "body_base64": base64.b64encode(content[:MAX_BODY_BYTES]).decode("ascii"),
            "body_too_large": len(content) > MAX_BODY_BYTES,
            "error": "",
        }
    except (OSError, http.client.HTTPException) as error:
        return {
            "status": 0,
            "body_base64": "",
            "body_too_large": False,
            "error": str(error)[:384],
        }
    finally:
        connection.close()


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)


def _stream(file: Any) -> tuple[bytes, bool]:
    file.flush()
    size = os.fstat(file.fileno()).st_size
    file.seek(0)
    return file.read(MAX_STREAM_BYTES), size > MAX_STREAM_BYTES


def main() -> None:
    request = json.load(sys.stdin)
    bodies = _requests(request["challenge"])
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = _start_service(stdout, stderr)
        started = _port_ready(process)
        addresses = _listen_ipv4() if started else []
        responses = [_request(body) for body in bodies] if started else []
        running = process.poll() is None
        exit_code = process.poll()
        _stop(process)
        stdout_bytes, stdout_large = _stream(stdout)
        stderr_bytes, stderr_large = _stream(stderr)

    encoded = lambda value: base64.b64encode(value).decode("ascii")
    print(
        json.dumps(
            {
                "format": "securebench.adapter-response/v2",
                "status": "observed",
                "observation": {
                    "server_started": started,
                    "process_running": running,
                    "process_exit": -1 if exit_code is None else exit_code,
                    "listen_ipv4": addresses,
                    "output_too_large": stdout_large or stderr_large,
                    "stdout_base64": encoded(stdout_bytes),
                    "stderr_base64": encoded(stderr_bytes),
                    "responses": responses,
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
