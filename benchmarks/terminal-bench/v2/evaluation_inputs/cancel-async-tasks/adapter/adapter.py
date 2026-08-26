"""Public assertion-free launcher for bounded async task scenarios."""

from __future__ import annotations

import json
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Any


CHILD_TIMEOUT_SECONDS = 6
INVOCATION_BYTES = 16
INVOCATION_TIMEOUT_SECONDS = 0.25
MAX_TASKS = 16


def _append_event(access: dict[str, str], nonce: str, event: str, data: str) -> None:
    body = json.dumps(
        {"nonce": nonce, "event": event, "data": data},
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        access["url"],
        data=body,
        headers={
            "Authorization": access["authorization"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        response.read(1)


class TaskService:
    """Own task effects while exposing only bounded invocation RPCs to Candidate code."""

    def __init__(
        self,
        challenge: dict[str, Any],
        access: dict[str, str],
    ) -> None:
        self.challenge = challenge
        self.access = access
        self.task_count = int(challenge["task_count"])
        if self.task_count < 1 or self.task_count > MAX_TASKS:
            raise ValueError("task count is outside the adapter bound")
        self.expected_started = min(
            self.task_count,
            int(challenge["max_concurrent"]),
        )
        if self.expected_started < 1:
            raise ValueError("concurrency limit is outside the adapter bound")
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(self.task_count + 4)
        self.listener.settimeout(0.05)
        self.port = self.listener.getsockname()[1]
        self.stop_event = threading.Event()
        self.claimed: set[int] = set()
        self.claim_lock = threading.Lock()
        self.started_count = 0
        self.started_lock = threading.Lock()
        self.ready = threading.Event()
        self.workers: list[threading.Thread] = []
        self.error: BaseException | None = None
        self.thread = threading.Thread(
            target=self._serve,
            name="securebench-task-service",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        try:
            self.listener.close()
        except OSError:
            pass
        self.thread.join(timeout=1)
        deadline = time.monotonic() + 3
        for worker in self.workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        if self.thread.is_alive() or any(worker.is_alive() for worker in self.workers):
            self.error = self.error or RuntimeError("task service cleanup timed out")

    def _serve(self) -> None:
        attempts = 0
        maximum_attempts = self.task_count * 4 + 8
        try:
            while (
                not self.stop_event.is_set()
                and attempts < maximum_attempts
                and len(self.claimed) < self.task_count
            ):
                try:
                    connection, _ = self.listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self.stop_event.is_set():
                        return
                    raise
                attempts += 1
                task_id = self._read_invocation(connection)
                if task_id is None or not self._claim(task_id):
                    connection.close()
                    continue
                worker = threading.Thread(
                    target=self._run_task,
                    args=(connection, task_id),
                    name=f"securebench-task-{task_id}",
                    daemon=True,
                )
                self.workers.append(worker)
                worker.start()
        except BaseException as exc:
            self.error = exc

    def _read_invocation(self, connection: socket.socket) -> int | None:
        connection.settimeout(INVOCATION_TIMEOUT_SECONDS)
        content = bytearray()
        try:
            while len(content) <= INVOCATION_BYTES:
                chunk = connection.recv(INVOCATION_BYTES + 1 - len(content))
                if not chunk:
                    return None
                content.extend(chunk)
                if b"\n" in content:
                    break
        except OSError:
            return None
        if content.count(b"\n") != 1 or not content.endswith(b"\n"):
            return None
        value = content[:-1]
        if not value.isascii() or not value.isdigit():
            return None
        task_id = int(value)
        if task_id < 0 or task_id >= self.task_count:
            return None
        connection.settimeout(None)
        return task_id

    def _claim(self, task_id: int) -> bool:
        with self.claim_lock:
            if task_id in self.claimed:
                return False
            self.claimed.add(task_id)
            return True

    def _run_task(self, connection: socket.socket, task_id: int) -> None:
        prefix = self.challenge["nonce_prefix"]
        data = str(task_id)
        try:
            _append_event(
                self.access,
                f"{prefix}_{task_id}_start",
                "task.started",
                data,
            )
            with self.started_lock:
                self.started_count += 1
                if self.started_count == self.expected_started:
                    self.ready.set()
            cancelled = self._client_closed(
                connection,
                self.challenge["work_ms"] / 1000,
            )
            if not cancelled:
                _append_event(
                    self.access,
                    f"{prefix}_{task_id}_complete",
                    "task.completed",
                    data,
                )
            else:
                _append_event(
                    self.access,
                    f"{prefix}_{task_id}_cancel",
                    "task.cancelled",
                    data,
                )
            time.sleep(self.challenge["cleanup_ms"] / 1000)
            _append_event(
                self.access,
                f"{prefix}_{task_id}_clean",
                "task.cleaned",
                data,
            )
            if not cancelled:
                try:
                    connection.sendall(b"D")
                except OSError:
                    pass
        except BaseException as exc:
            self.error = exc
        finally:
            connection.close()

    @staticmethod
    def _client_closed(connection: socket.socket, duration: float) -> bool:
        deadline = time.monotonic() + duration
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            readable, _, _ = select.select([connection], [], [], remaining)
            if not readable:
                return False
            try:
                # Any post-invocation client bytes are invalid; EOF means the
                # awaiting task was cancelled or its process exited.
                connection.recv(1)
            except OSError:
                pass
            return True


def main() -> None:
    request = json.load(sys.stdin)
    challenge = request["challenge"]
    access = request["trusted_helpers"]["lifecycle"]
    child: subprocess.Popen[bytes] | None = None
    signal_received = threading.Event()
    child_done = threading.Event()
    signal_forwarded = False
    signal_error: list[BaseException] = []
    service = TaskService(challenge, access)

    def forward_signal(_signum: int, _frame: object) -> None:
        signal_received.set()

    def coordinate_signal() -> None:
        nonlocal signal_forwarded
        signal_received.wait(timeout=CHILD_TIMEOUT_SECONDS + 1)
        if not signal_received.is_set():
            return
        while not service.ready.wait(timeout=0.05):
            if child_done.is_set():
                return
        current_child = child
        if current_child is None or current_child.poll() is not None:
            return
        try:
            _append_event(
                access,
                f"{challenge['nonce_prefix']}_signal",
                "adapter.signal_forwarded",
                "SIGINT",
            )
        except BaseException as exc:
            signal_error.append(exc)
            return
        try:
            current_child.send_signal(signal.SIGINT)
        except OSError:
            return
        signal_forwarded = True

    previous_handler: Any = signal.signal(signal.SIGINT, forward_signal)
    signal_thread = threading.Thread(
        target=coordinate_signal,
        name="securebench-signal-coordinator",
        daemon=True,
    )
    child_started = False
    child_exit_code = 127
    timed_out = False
    service.start()
    signal_thread.start()
    try:
        driver_request = {
            "challenge": challenge,
            "task_service": {"host": "127.0.0.1", "port": service.port},
        }
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("driver.py"))],
            cwd="/app",
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        child_started = True
        input_stream = child.stdin
        if input_stream is None:
            raise OSError("candidate driver input channel is unavailable")
        input_stream.write(
            json.dumps(driver_request, separators=(",", ":")).encode("utf-8")
        )
        input_stream.close()
        try:
            child_exit_code = child.wait(timeout=CHILD_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            child_exit_code = child.wait(timeout=1)
    except (OSError, ValueError):
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=1)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        child_done.set()
        if signal_received.is_set():
            signal_thread.join(timeout=2)
            if signal_thread.is_alive():
                signal_error.append(RuntimeError("signal coordinator cleanup timed out"))
        service.close()

    if service.error is not None or signal_error:
        raise RuntimeError("task service failed")
    observation = {
        "child_started": child_started,
        "child_exit_code": child_exit_code,
        "signal_received": signal_received.is_set(),
        "signal_forwarded": signal_forwarded,
        "timed_out": timed_out,
    }
    print(
        json.dumps(
            {
                "format": "securebench.adapter-response/v2",
                "status": "observed",
                "observation": observation,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
