"""Public assertion-free observer for a restartable Windows/QEMU bundle."""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
from typing import Any

from PIL import Image


LAUNCHER = Path("/app/start-windows.sh")
DISK = Path("/app/isos/win311.img")
MONITOR = "/tmp/qemu-monitor.sock"
KEYS = {"f1", "alt-tab", "f10", "alt-f4", "ctrl-esc"}
PORTS = (80, 5_901)
MAX_STREAM_BYTES = 16_384
MAX_HTTP_BYTES = 4_096
MAX_MONITOR_BYTES = 8_192
MAX_SNAPSHOT_BYTES = 8 * 1_024 * 1_024
MAX_FRAME_PIXELS = 1_024 * 1_024


def _challenge(value: Any) -> list[str]:
    if not isinstance(value, dict) or set(value) != {"keys"}:
        raise ValueError("challenge must contain exactly one key sequence")
    keys = value["keys"]
    if (
        not isinstance(keys, list)
        or not 1 <= len(keys) <= len(KEYS)
        or len(set(keys)) != len(keys)
        or any(not isinstance(key, str) or key not in KEYS for key in keys)
    ):
        raise ValueError("key sequence is invalid")
    return keys


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _start_launcher(stdout: Any, stderr: Any) -> tuple[int, bool]:
    process = subprocess.Popen(
        ["/bin/sh", str(LAUNCHER)],
        cwd="/app",
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    try:
        return process.wait(timeout=20), False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)
        return process.returncode, True


def _listening_ports() -> list[int]:
    ports: set[int] = set()
    for source in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            lines = source.read_text(encoding="ascii").splitlines()[1:]
        except (OSError, UnicodeError):
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 4 or fields[3] != "0A":
                continue
            try:
                port = int(fields[1].rsplit(":", 1)[1], 16)
            except (IndexError, ValueError):
                continue
            if port in PORTS:
                ports.add(port)
    return sorted(ports)


def _wait_for_runtime() -> list[int]:
    deadline = time.monotonic() + 20
    ports: list[int] = []
    while time.monotonic() < deadline:
        ports = _listening_ports()
        if all(port in ports for port in PORTS) and Path(MONITOR).is_socket():
            break
        time.sleep(0.2)
    if all(port in ports for port in PORTS):
        time.sleep(12)
    return _listening_ports()


def _qemu_processes() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for process_dir in sorted(
        (path for path in Path("/proc").iterdir() if path.name.isdigit()),
        key=lambda path: int(path.name),
    ):
        try:
            raw = (process_dir / "cmdline").read_bytes()
            arguments = [
                item.decode("utf-8", errors="replace")[:2_048]
                for item in raw.split(b"\0")
                if item
            ][:64]
            executable = os.readlink(process_dir / "exe")[:2_048]
        except OSError:
            continue
        if not arguments or "qemu-system" not in Path(arguments[0]).name:
            continue
        records.append(
            {
                "pid": int(process_dir.name),
                "executable": executable,
                "arguments": arguments,
            }
        )
        if len(records) == 4:
            break
    return records


def _http_observation() -> dict[str, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", 80, timeout=4)
    try:
        connection.request("GET", "/", headers={"Connection": "close"})
        response = connection.getresponse()
        body = response.read(MAX_HTTP_BYTES + 1)
        return {
            "status": int(response.status),
            "body_base64": base64.b64encode(body[:MAX_HTTP_BYTES]).decode("ascii"),
            "body_too_large": len(body) > MAX_HTTP_BYTES,
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


def _monitor_command(command: str) -> tuple[bytes, str]:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(2)
    output = bytearray()
    try:
        client.connect(MONITOR)
        try:
            output.extend(client.recv(MAX_MONITOR_BYTES))
        except TimeoutError:
            pass
        client.sendall(command.encode("ascii") + b"\n")
        deadline = time.monotonic() + 2
        while len(output) < MAX_MONITOR_BYTES and time.monotonic() < deadline:
            try:
                chunk = client.recv(MAX_MONITOR_BYTES - len(output))
            except TimeoutError:
                break
            if not chunk:
                break
            output.extend(chunk)
        return bytes(output), ""
    except OSError as error:
        return bytes(output), str(error)[:384]
    finally:
        client.close()


def _snapshot(path: Path) -> tuple[bytes | None, int, int, str]:
    try:
        completed = subprocess.run(
            [
                "/usr/bin/vncsnapshot",
                "-quiet",
                "-allowblank",
                "-count",
                "1",
                "127.0.0.1:1",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=8,
            check=False,
        )
        if completed.returncode != 0:
            return None, 0, 0, completed.stderr.decode(errors="replace")[:384]
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return None, 0, 0, "snapshot exceeded byte limit"
        with Image.open(path) as image:
            if (
                image.width <= 0
                or image.height <= 0
                or image.width * image.height > MAX_FRAME_PIXELS
            ):
                return None, 0, 0, "snapshot dimensions exceeded limit"
            rgb = image.convert("RGB")
            return rgb.tobytes(), rgb.width, rgb.height, ""
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        return None, 0, 0, str(error)[:384]


def _frame_observations(keys: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    baseline, width, height, baseline_error = _snapshot(Path("/tmp/baseline.jpg"))
    baseline_record = {
        "width": width,
        "height": height,
        "capture_error": baseline_error,
        "sha256": "" if baseline is None else hashlib.sha256(baseline).hexdigest(),
    }
    frames: list[dict[str, Any]] = []
    for index, key in enumerate(keys):
        monitor_bytes, monitor_error = _monitor_command("sendkey " + key)
        time.sleep(1)
        frame, frame_width, frame_height, capture_error = _snapshot(
            Path(f"/tmp/frame-{index}.jpg")
        )
        comparable = (
            baseline is not None
            and frame is not None
            and frame_width == width
            and frame_height == height
            and len(frame) == len(baseline)
        )
        changed = (
            sum(left != right for left, right in zip(baseline, frame))
            if comparable and baseline is not None and frame is not None
            else 0
        )
        frames.append(
            {
                "key": key,
                "width": frame_width,
                "height": frame_height,
                "different_components": changed,
                "total_components": len(baseline) if comparable and baseline is not None else 0,
                "sha256": "" if frame is None else hashlib.sha256(frame).hexdigest(),
                "monitor_base64": base64.b64encode(monitor_bytes).decode("ascii"),
                "monitor_error": monitor_error,
                "capture_error": capture_error,
            }
        )
    return baseline_record, frames


def _stream(file: Any) -> tuple[str, bool]:
    file.flush()
    size = os.fstat(file.fileno()).st_size
    file.seek(0)
    content = file.read(MAX_STREAM_BYTES)
    return base64.b64encode(content).decode("ascii"), size > MAX_STREAM_BYTES


def main() -> None:
    request = json.load(__import__("sys").stdin)
    keys = _challenge(request["challenge"])
    disk_before, disk_size = _digest(DISK)
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        launcher_exit, launcher_timed_out = _start_launcher(stdout, stderr)
        ports = _wait_for_runtime() if launcher_exit == 0 else _listening_ports()
        processes = _qemu_processes()
        http = _http_observation()
        monitor_bytes, monitor_error = _monitor_command("info version")
        baseline, frames = _frame_observations(keys)
        disk_after, disk_size_after = _digest(DISK)
        stdout_base64, stdout_too_large = _stream(stdout)
        stderr_base64, stderr_too_large = _stream(stderr)

    observation = {
        "launcher_exit": launcher_exit,
        "launcher_timed_out": launcher_timed_out,
        "qemu_processes": processes,
        "listen_ports": ports,
        "disk_sha256_before": disk_before,
        "disk_sha256_after": disk_after,
        "disk_size_before": disk_size,
        "disk_size_after": disk_size_after,
        "http": http,
        "monitor_base64": base64.b64encode(monitor_bytes).decode("ascii"),
        "monitor_error": monitor_error,
        "baseline": baseline,
        "frames": frames,
        "output_too_large": stdout_too_large or stderr_too_large,
        "stdout_base64": stdout_base64,
        "stderr_base64": stderr_base64,
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
