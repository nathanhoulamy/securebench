"""Public assertion-free Adapter for bounded headless-terminal scenarios."""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path, PurePosixPath
import selectors
import signal
import stat
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.request


APP = Path("/app")
CASE_ROOT = APP / ".securebench-case"
HOME = CASE_ROOT / "home"
OBSERVED_ROOT = CASE_ROOT / "observed"
SERVER_ROOT = CASE_ROOT / "server"
DRIVER = Path(__file__).resolve().with_name("driver.py")
MAX_CHALLENGE_FIELD_BYTES = 6_144
MAX_DRIVER_STREAM_BYTES = 8_192
MAX_OBSERVED_BYTES = 4_096
MAX_WAIT_MS = 5_000
DRIVER_SECONDS = 25
STOP_GRACE_SECONDS = 2.0

# Read-only runtime resource vendored alongside this Adapter (see
# ../vim-runtime/PROVENANCE.md): the exact `vim`/`vim-common`/`vim-runtime`/
# `xxd`/`libgpm2`/`libsodium23` packages upstream's own verifier installs at
# verification time (`apt-get install -y vim`), extracted ahead of time so
# the networkless Evaluation container never needs to fetch them.
VIM_RUNTIME_ROOT = Path("/opt/securebench/runtimes/vim")
VIM_BIN_DIR = VIM_RUNTIME_ROOT / "usr" / "bin"
VIM_LIB_DIR = VIM_RUNTIME_ROOT / "usr" / "lib" / "x86_64-linux-gnu"
VIM_SHARE_DIR = VIM_RUNTIME_ROOT / "usr" / "share" / "vim"
VIM_RUNTIME_DIR = VIM_SHARE_DIR / "vim90"


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


def _decode(value: Any, *, maximum: int = MAX_CHALLENGE_FIELD_BYTES) -> bytes:
    if not isinstance(value, str):
        raise ValueError("encoded challenge field must be text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("challenge field is not valid base64") from error
    if len(decoded) > maximum:
        raise ValueError("decoded challenge field exceeds limit")
    return decoded


def _relative_observation_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str):
        raise ValueError("observation path must be text")
    path = PurePosixPath(value)
    if (
        str(path) != value
        or path.is_absolute()
        or len(path.parts) < 2
        or path.parts[0] != "observed"
        or ".." in path.parts
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError("observation path is outside the case root")
    return path


def _prepare_challenge(challenge: Any) -> tuple[dict[str, Any], Path, int, str]:
    if not isinstance(challenge, dict):
        raise ValueError("challenge must be an object")
    startup = _decode(challenge["startup_base64"])
    server_body = _decode(challenge["server_body_base64"])
    try:
        startup_text = startup.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("startup file must be UTF-8") from error

    raw_steps = challenge["steps"]
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 16:
        raise ValueError("challenge must contain bounded terminal steps")
    steps: list[dict[str, Any]] = []
    total_wait = 0
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            raise ValueError("terminal step must be an object")
        keys = _decode(raw_step["keys_base64"])
        try:
            keys_text = keys.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("keystrokes must be UTF-8") from error
        wait_ms = raw_step["wait_ms"]
        if isinstance(wait_ms, bool) or not isinstance(wait_ms, int):
            raise ValueError("terminal wait must be an integer")
        if not 0 <= wait_ms <= MAX_WAIT_MS:
            raise ValueError("terminal wait exceeds adapter limit")
        total_wait += wait_ms
        steps.append({"keys": keys_text, "wait_ms": wait_ms})
    if total_wait > 15_000:
        raise ValueError("aggregate terminal wait exceeds adapter limit")

    relative_path = _relative_observation_path(challenge["file_path"])
    port = challenge["http_port"]
    if isinstance(port, bool) or not isinstance(port, int):
        raise ValueError("HTTP port must be an integer")
    if port != 0 and not 10_240 <= port <= 20_000:
        raise ValueError("HTTP port is outside the adapter range")
    http_path = challenge["http_path"]
    if (
        not isinstance(http_path, str)
        or not http_path.startswith("/")
        or "\r" in http_path
        or "\n" in http_path
        or "\x00" in http_path
    ):
        raise ValueError("HTTP path is invalid")

    CASE_ROOT.mkdir(mode=0o700)
    HOME.mkdir(mode=0o700)
    OBSERVED_ROOT.mkdir(mode=0o700)
    SERVER_ROOT.mkdir(mode=0o700)
    (HOME / ".bashrc").write_text(startup_text, encoding="utf-8")
    (SERVER_ROOT / "index.html").write_bytes(server_body)
    return {"steps": steps}, CASE_ROOT / relative_path, port, http_path


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
            remaining = MAX_DRIVER_STREAM_BYTES - len(buffers[label])
            buffers[label].extend(chunk[: max(0, remaining) + 1])
            if len(buffers[label]) > MAX_DRIVER_STREAM_BYTES:
                exceeded = True
                break
            if len(chunk) < 8_192:
                break
    return exceeded


FileObservation = tuple[bool, bool, bytes]
HttpObservation = tuple[bool, int, bool, bytes, str]


def _run_driver(
    request: dict[str, Any],
    observed_path: Path,
    http_port: int,
    http_path: str,
) -> tuple[str, int | None, bytes, bytes, FileObservation, HttpObservation]:
    environment = os.environ.copy()
    environment["HOME"] = str(HOME)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PATH"] = f"{VIM_BIN_DIR}:{environment.get('PATH', '')}"
    environment["VIM"] = str(VIM_SHARE_DIR)
    environment["VIMRUNTIME"] = str(VIM_RUNTIME_DIR)
    existing_ld_path = environment.get("LD_LIBRARY_PATH", "")
    environment["LD_LIBRARY_PATH"] = (
        f"{VIM_LIB_DIR}:{existing_ld_path}" if existing_ld_path else str(VIM_LIB_DIR)
    )

    ready_read_fd, ready_write_fd = os.pipe()
    environment["SECUREBENCH_READY_FD"] = str(ready_write_fd)
    try:
        process = subprocess.Popen(
            [sys.executable, str(DRIVER)],
            cwd=APP,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            pass_fds=(ready_write_fd,),
        )
    finally:
        os.close(ready_write_fd)
    if process.stdin is None or process.stdout is None or process.stderr is None:
        os.close(ready_read_fd)
        raise RuntimeError("driver pipes were not created")
    process.stdin.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
    process.stdin.flush()

    selector = selectors.DefaultSelector()
    buffers = {"stdout": bytearray(), "stderr": bytearray(), "ready": bytearray()}
    for label, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, label)
    os.set_blocking(ready_read_fd, False)
    selector.register(ready_read_fd, selectors.EVENT_READ, "ready")

    status = "observed"
    exit_code: int | None = None
    reached_ready = False
    file_observation: FileObservation = (False, False, b"")
    http_observation: HttpObservation = (False, 0, False, b"", "")
    deadline = time.monotonic() + DRIVER_SECONDS
    try:
        while True:
            if buffers["ready"]:
                reached_ready = True
                break
            if process.poll() is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = "timeout"
                break
            if _read_available(selector, buffers, min(0.1, remaining)):
                status = "too_large"
                break

        if status == "observed":
            # The Candidate terminal -- and anything it left running, such as
            # a background service -- is still alive here: the driver either
            # signalled readiness explicitly, or it had already exited on its
            # own (for example, a Candidate import error). Either way this is
            # the moment to observe bounded evidence, matching upstream's
            # in-process ordering, before any teardown below.
            file_observation = _observe_file(observed_path)
            http_observation = _observe_http(http_port, http_path)

        if reached_ready:
            try:
                process.stdin.write(b"stop\n")
                process.stdin.flush()
            except OSError:
                pass
            try:
                process.stdin.close()
            except OSError:
                pass
            stop_deadline = time.monotonic() + STOP_GRACE_SECONDS
            while process.poll() is None:
                remaining = stop_deadline - time.monotonic()
                if remaining <= 0:
                    break
                if _read_available(selector, buffers, min(0.1, max(remaining, 0.0))):
                    status = "too_large"
                    break

        exit_code = process.poll()
        if status == "observed" and exit_code is None:
            status = "timeout"

        drain_deadline = time.monotonic() + 0.5
        while selector.get_map() and time.monotonic() < drain_deadline:
            if _read_available(selector, buffers, 0.05):
                status = "too_large"
                break
    finally:
        _stop_process_group(process)
        selector.close()
        process.stdout.close()
        process.stderr.close()
        try:
            os.close(ready_read_fd)
        except OSError:
            pass
    return (
        status,
        exit_code,
        bytes(buffers["stdout"]),
        bytes(buffers["stderr"]),
        file_observation,
        http_observation,
    )


def _observe_file(path: Path) -> tuple[bool, bool, bytes]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False, False, b""
    except OSError:
        return True, True, b""
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            return True, True, b""
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read(MAX_OBSERVED_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return True, len(content) > MAX_OBSERVED_BYTES, content[:MAX_OBSERVED_BYTES]


def _observe_http(port: int, path: str) -> tuple[bool, int, bool, bytes, str]:
    if port == 0:
        return False, 0, False, b"", ""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method="GET",
        headers={"Connection": "close"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            body = response.read(MAX_OBSERVED_BYTES + 1)
            return (
                True,
                int(response.status),
                len(body) > MAX_OBSERVED_BYTES,
                body[:MAX_OBSERVED_BYTES],
                "",
            )
    except (OSError, urllib.error.URLError) as error:
        return True, 0, False, b"", str(error)[:384]


def main() -> None:
    request = json.load(sys.stdin)
    driver_request, observed_path, http_port, http_path = _prepare_challenge(
        request["challenge"]
    )
    (
        status,
        exit_code,
        driver_stdout,
        driver_stderr,
        file_observation,
        http_observation,
    ) = _run_driver(driver_request, observed_path, http_port, http_path)
    if status == "timeout":
        _candidate_error("candidate_timeout", "Candidate terminal driver exceeded its time limit")
        return
    if status == "too_large":
        _candidate_error(
            "candidate_output_too_large",
            "Candidate terminal driver exceeded a bounded output limit",
        )
        return

    file_exists, file_too_large, file_content = file_observation
    http_attempted, http_status, http_too_large, http_body, http_error = http_observation
    encoded = lambda value: base64.b64encode(value).decode("ascii")
    print(
        json.dumps(
            {
                "format": "securebench.adapter-response/v2",
                "status": "observed",
                "observation": {
                    "driver_exit": exit_code,
                    "driver_stdout_base64": encoded(driver_stdout),
                    "driver_stderr_base64": encoded(driver_stderr),
                    "file_exists": file_exists,
                    "file_too_large": file_too_large,
                    "file_base64": encoded(file_content),
                    "http_attempted": http_attempted,
                    "http_status": http_status,
                    "http_too_large": http_too_large,
                    "http_body_base64": encoded(http_body),
                    "http_error": http_error,
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
