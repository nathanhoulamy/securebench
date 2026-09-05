"""Public assertion-free runner for one bounded KVStore gRPC scenario."""

from __future__ import annotations

import base64
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


SERVER = Path("/app/server.py")
DEPENDENCIES = Path("/app/kv_store_dependencies")
PORT = 5_328
STARTUP_SECONDS = 10
RPC_SECONDS = 5
MAX_KEY_BYTES = 256
MAX_STREAM_BYTES = 32_768
MAX_FRAME_BYTES = 65_536
MAX_GRPC_BYTES = 4_096


def _operations(challenge: Any) -> list[dict[str, Any]]:
    if not isinstance(challenge, dict) or set(challenge) != {"operations"}:
        raise ValueError("challenge must contain exactly the operations list")
    raw = challenge["operations"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= 8:
        raise ValueError("operations must be a bounded non-empty list")
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("operation must be an object")
        rpc = item.get("rpc")
        key = item.get("key")
        if rpc not in {"get", "set"} or not isinstance(key, str):
            raise ValueError("operation has an invalid RPC or key")
        if len(key.encode("utf-8")) > MAX_KEY_BYTES:
            raise ValueError("operation key exceeds limit")
        if rpc == "get":
            if set(item) != {"rpc", "key"}:
                raise ValueError("GetVal operation has invalid fields")
            result.append({"rpc": rpc, "key": key})
        else:
            value = item.get("value")
            if (
                set(item) != {"rpc", "key", "value"}
                or type(value) is not int
                or not -(2**31) <= value < 2**31
            ):
                raise ValueError("SetVal operation has invalid fields")
            result.append({"rpc": rpc, "key": key, "value": value})
    return result


def _varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _request_message(operation: dict[str, Any]) -> bytes:
    key = operation["key"].encode("utf-8")
    message = b"\x0a" + _varint(len(key)) + key
    if operation["rpc"] == "set":
        message += b"\x10" + _varint(operation["value"])
    return message


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("truncated protobuf varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
    raise ValueError("oversized protobuf varint")


def _response_value(message: bytes) -> int:
    offset = 0
    value = 0
    found = False
    while offset < len(message):
        tag, offset = _read_varint(message, offset)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            item, offset = _read_varint(message, offset)
            if field == 1:
                value = item & 0xFFFFFFFF
                found = True
        elif wire == 1:
            offset += 8
        elif wire == 2:
            length, offset = _read_varint(message, offset)
            offset += length
        elif wire == 5:
            offset += 4
        else:
            raise ValueError("unsupported protobuf wire type")
        if offset > len(message):
            raise ValueError("truncated protobuf response")
    if not found:
        return 0
    return value - (1 << 32) if value >= 1 << 31 else value


def _hpack_integer(value: int, prefix_bits: int, first: int = 0) -> bytes:
    maximum = (1 << prefix_bits) - 1
    if value < maximum:
        return bytes((first | value,))
    result = bytearray((first | maximum,))
    value -= maximum
    while value >= 128:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _hpack_string(value: str) -> bytes:
    raw = value.encode("ascii")
    return _hpack_integer(len(raw), 7) + raw


def _literal(name_index: int, value: str) -> bytes:
    return _hpack_integer(name_index, 4) + _hpack_string(value)


def _new_literal(name: str, value: str) -> bytes:
    return b"\x00" + _hpack_string(name) + _hpack_string(value)


def _hpack_decode_integer(
    data: bytes,
    offset: int,
    prefix_bits: int,
) -> tuple[int, int]:
    if offset >= len(data):
        raise ValueError("truncated HPACK integer")
    maximum = (1 << prefix_bits) - 1
    value = data[offset] & maximum
    offset += 1
    if value < maximum:
        return value, offset
    shift = 0
    while True:
        if offset >= len(data) or shift > 56:
            raise ValueError("malformed HPACK integer")
        byte = data[offset]
        offset += 1
        value += (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def _hpack_decode_string(data: bytes, offset: int) -> tuple[str, int]:
    if offset >= len(data) or data[offset] & 0x80:
        raise ValueError("Huffman-coded HPACK strings are unsupported")
    length, offset = _hpack_decode_integer(data, offset, 7)
    end = offset + length
    if end > len(data):
        raise ValueError("truncated HPACK string")
    try:
        return data[offset:end].decode("ascii"), end
    except UnicodeDecodeError as error:
        raise ValueError("non-ASCII HPACK string") from error


def _hpack_headers(data: bytes) -> list[tuple[str, str]]:
    static = {
        1: (":authority", ""),
        4: (":path", "/"),
        8: (":status", "200"),
        31: ("content-type", ""),
    }
    dynamic: list[tuple[str, str]] = []

    def indexed(index: int) -> tuple[str, str]:
        if index in static:
            return static[index]
        dynamic_index = index - 62
        if 0 <= dynamic_index < len(dynamic):
            return dynamic[dynamic_index]
        raise ValueError("unsupported HPACK table index")

    offset = 0
    result: list[tuple[str, str]] = []
    while offset < len(data):
        first = data[offset]
        if first & 0x80:
            index, offset = _hpack_decode_integer(data, offset, 7)
            result.append(indexed(index))
            continue
        if first & 0x40:
            name_index, offset = _hpack_decode_integer(data, offset, 6)
            if name_index:
                name = indexed(name_index)[0]
            else:
                name, offset = _hpack_decode_string(data, offset)
            value, offset = _hpack_decode_string(data, offset)
            field = (name, value)
            dynamic.insert(0, field)
            result.append(field)
            continue
        if first & 0x20:
            _, offset = _hpack_decode_integer(data, offset, 5)
            continue
        name_index, offset = _hpack_decode_integer(data, offset, 4)
        if name_index:
            name = indexed(name_index)[0]
        else:
            name, offset = _hpack_decode_string(data, offset)
        value, offset = _hpack_decode_string(data, offset)
        result.append((name, value))
    return result


def _headers(path: str) -> bytes:
    return b"".join(
        (
            b"\x83",  # :method: POST
            b"\x86",  # :scheme: http
            _literal(4, path),  # :path
            _literal(1, f"127.0.0.1:{PORT}"),  # :authority
            _literal(31, "application/grpc"),  # content-type
            _new_literal("te", "trailers"),
        )
    )


def _frame(frame_type: int, flags: int, stream: int, payload: bytes) -> bytes:
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError("HTTP/2 frame exceeds limit")
    return (
        len(payload).to_bytes(3, "big")
        + bytes((frame_type, flags))
        + (stream & 0x7FFFFFFF).to_bytes(4, "big")
        + payload
    )


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise OSError("gRPC connection closed early")
        chunks.extend(chunk)
    return bytes(chunks)


def _grpc_call(path: str, message: bytes) -> int:
    body = b"\x00" + len(message).to_bytes(4, "big") + message
    with socket.create_connection(("127.0.0.1", PORT), timeout=RPC_SECONDS) as connection:
        connection.settimeout(RPC_SECONDS)
        connection.sendall(
            b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"
            + _frame(4, 0, 0, b"")
            + _frame(1, 4, 1, _headers(path))
            + _frame(0, 1, 1, body)
        )
        data = bytearray()
        finished = False
        trailers: list[tuple[str, str]] | None = None
        while not finished:
            header = _receive_exact(connection, 9)
            length = int.from_bytes(header[:3], "big")
            frame_type, flags = header[3], header[4]
            stream = int.from_bytes(header[5:], "big") & 0x7FFFFFFF
            if length > MAX_FRAME_BYTES:
                raise ValueError("server frame exceeds limit")
            payload = _receive_exact(connection, length)
            if frame_type == 4 and stream == 0 and not flags & 1:
                connection.sendall(_frame(4, 1, 0, b""))
            elif frame_type == 0 and stream == 1:
                if flags & 8:
                    if not payload:
                        raise ValueError("invalid padded DATA frame")
                    padding = payload[0]
                    if padding + 1 > len(payload):
                        raise ValueError("invalid DATA padding")
                    payload = payload[1 : len(payload) - padding]
                data.extend(payload)
                if len(data) > MAX_GRPC_BYTES + 5:
                    raise ValueError("gRPC response exceeds limit")
            elif frame_type == 1 and stream == 1 and flags & 1:
                if not flags & 4:
                    raise ValueError("continued gRPC trailers are unsupported")
                if flags & 8:
                    if not payload:
                        raise ValueError("invalid padded HEADERS frame")
                    padding = payload[0]
                    if padding + 1 > len(payload):
                        raise ValueError("invalid HEADERS padding")
                    payload = payload[1 : len(payload) - padding]
                if flags & 0x20:
                    if len(payload) < 5:
                        raise ValueError("invalid prioritized HEADERS frame")
                    payload = payload[5:]
                trailers = _hpack_headers(payload)
            elif frame_type in {3, 7}:
                raise OSError("gRPC stream was rejected")
            if stream == 1 and flags & 1:
                finished = True
    if len(data) < 5 or data[0] != 0:
        raise ValueError("missing or compressed gRPC response")
    statuses = [] if trailers is None else [
        value for name, value in trailers if name == "grpc-status"
    ]
    if statuses != ["0"]:
        raise ValueError("gRPC call did not complete successfully")
    length = int.from_bytes(data[1:5], "big")
    if length > MAX_GRPC_BYTES or len(data) != length + 5:
        raise ValueError("malformed gRPC message framing")
    return _response_value(bytes(data[5:]))


def _child_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (MAX_STREAM_BYTES + 1, MAX_STREAM_BYTES + 1),
    )


def _start_service(stdout: Any, stderr: Any) -> subprocess.Popen[bytes]:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(DEPENDENCIES),
        }
    )
    return subprocess.Popen(
        [sys.executable, str(SERVER)],
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


def _run(operation: dict[str, Any]) -> dict[str, Any]:
    path = "/KVStore/GetVal" if operation["rpc"] == "get" else "/KVStore/SetVal"
    try:
        value = _grpc_call(path, _request_message(operation))
        return {"status": "returned", "val": value, "error": ""}
    except (OSError, ValueError) as error:
        return {"status": "error", "val": 0, "error": str(error)[:384]}


def main() -> None:
    request = json.load(sys.stdin)
    operations = _operations(request["challenge"])
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = _start_service(stdout, stderr)
        started = _port_ready(process)
        responses = [_run(operation) for operation in operations] if started else []
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
