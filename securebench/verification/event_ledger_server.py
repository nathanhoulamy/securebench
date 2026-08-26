"""Bounded data plane for ``securebench.append-only-event-ledger/v1``."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


MAX_CONFIG_BYTES = 256 * 1024
MAX_CREDENTIAL_BYTES = 512
MAX_REQUEST_TARGET_BYTES = 2048
MAX_HEADER_BYTES = 16 * 1024
EVENT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
NONCE = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _read_json(path: Path, maximum_bytes: int) -> Any:
    with path.open("rb") as stream:
        content = stream.read(maximum_bytes + 1)
    if len(content) > maximum_bytes:
        raise ValueError("configuration exceeded its bound")
    return json.loads(content)


def _strict_event(body: bytes, maximum_bytes: int) -> tuple[str, str, str]:
    if len(body) > maximum_bytes:
        raise ValueError("event body exceeded its bound")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate event field")
            value[key] = item
        return value

    value = json.loads(
        body.decode("utf-8", errors="strict"),
        object_pairs_hook=pairs,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(value, dict) or set(value) != {"nonce", "event", "data"}:
        raise ValueError("event shape is invalid")
    nonce, event, data = value["nonce"], value["event"], value["data"]
    if (
        not isinstance(nonce, str)
        or NONCE.fullmatch(nonce) is None
        or not isinstance(event, str)
        or EVENT_NAME.fullmatch(event) is None
        or not isinstance(data, str)
        or len(data.encode("utf-8")) > maximum_bytes
    ):
        raise ValueError("event fields are invalid")
    return nonce, event, data


class EventLedgerState:
    """Thread-safe append-only event state owned by one helper Evaluation."""

    def __init__(self, config: dict[str, Any], token: str, state_dir: Path) -> None:
        self.challenge_id = config["challenge_id"]
        self.evaluation_id = config["evaluation_id"]
        self.path = config["settings"].get("path", "/events")
        self.max_events = config["limits"]["max_events"]
        self.max_event_bytes = config["limits"]["max_event_bytes"]
        self.token = token
        self.state_dir = state_dir
        self.events_path = state_dir / "events.jsonl"
        self.truncated_path = state_dir / "truncated.flag"
        self.start_ns = time.monotonic_ns()
        self.sequence = 0
        self.lock = threading.Lock()

    def mark_truncated(self) -> None:
        self.truncated_path.touch(exist_ok=True)

    def at_capacity(self) -> bool:
        with self.lock:
            return self.sequence >= self.max_events

    def append(self, record: dict[str, Any]) -> bool:
        with self.lock:
            if self.sequence >= self.max_events:
                self.truncated_path.touch(exist_ok=True)
                return False
            record["sequence"] = self.sequence
            record["elapsed_us"] = max(
                0,
                (time.monotonic_ns() - self.start_ns) // 1000,
            )
            self.sequence += 1
            encoded = json.dumps(
                record,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            with self.events_path.open("ab", buffering=0) as stream:
                stream.write(encoded)
                os.fsync(stream.fileno())
        return True


class EventLedgerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: EventLedgerState) -> None:
        super().__init__(address, EventLedgerHandler)
        self.event_ledger_state = state

    def handle_error(self, request: object, client_address: object) -> None:
        return


class EventLedgerHandler(BaseHTTPRequestHandler):
    server: EventLedgerServer
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_attempt()

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_attempt()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_attempt()

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_attempt()

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_attempt()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_attempt()

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_attempt()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _record_attempt(self) -> None:
        state = self.server.event_ledger_state
        self.close_connection = True
        if state.at_capacity():
            state.mark_truncated()
            self._respond(429)
            return

        target_bytes = self.path.encode("utf-8", errors="replace")
        target_truncated = len(target_bytes) > MAX_REQUEST_TARGET_BYTES
        target = target_bytes[:MAX_REQUEST_TARGET_BYTES].decode("utf-8", errors="ignore")
        try:
            request_path = urlsplit(target).path
        except ValueError:
            request_path = ""
        target_valid = (
            not target_truncated
            and target.startswith("/")
            and not target.startswith("//")
            and "\\" not in target
            and "#" not in target
            and all(0x21 <= ord(character) <= 0x7E for character in target)
        )
        path_matched = target_valid and request_path == state.path

        authorizations = self.headers.get_all("Authorization", [])
        authenticated = len(authorizations) == 1 and hmac.compare_digest(
            authorizations[0], f"Bearer {state.token}"
        )
        content_types = self.headers.get_all("Content-Type", [])
        content_type_valid = (
            len(content_types) == 1
            and content_types[0].lower() == "application/json"
        )
        transfer_encodings = self.headers.get_all("Transfer-Encoding", [])
        content_lengths = self.headers.get_all("Content-Length", [])
        try:
            content_length = int(content_lengths[0]) if len(content_lengths) == 1 else 0
            if content_length < 0:
                raise ValueError
        except ValueError:
            content_length = 0
            ambiguous_length = True
        else:
            ambiguous_length = len(content_lengths) != 1
        header_bytes = sum(
            len(name.encode("utf-8", errors="replace"))
            + len(value.encode("utf-8", errors="replace"))
            + 4
            for name, value in self.headers.items()
        )

        body_truncated = content_length > state.max_event_bytes
        read_length = min(content_length, state.max_event_bytes)
        body = self.rfile.read(read_length) if read_length else b""
        if len(body) != read_length:
            body_truncated = True
        nonce = event = data = ""
        event_valid = False
        if not body_truncated and not ambiguous_length and not transfer_encodings:
            try:
                nonce, event, data = _strict_event(body, state.max_event_bytes)
            except (UnicodeError, ValueError):
                pass
            else:
                event_valid = True

        if target_truncated:
            status = 414
            state.mark_truncated()
        elif not target_valid:
            status = 400
        elif self.command != "POST":
            status = 405
        elif not path_matched:
            status = 404
        elif header_bytes > MAX_HEADER_BYTES:
            status = 431
            state.mark_truncated()
        elif transfer_encodings or ambiguous_length:
            status = 400
            body_truncated = True
            state.mark_truncated()
        elif body_truncated:
            status = 413
            state.mark_truncated()
        elif not authenticated:
            status = 401
        elif not content_type_valid or not event_valid:
            status = 400
        else:
            status = 202

        accepted = status == 202
        recorded = state.append(
            {
                "challenge_id": state.challenge_id,
                "evaluation_id": state.evaluation_id,
                "method": self.command,
                "target": target,
                "target_truncated": target_truncated,
                "path_matched": path_matched,
                "authenticated": authenticated,
                "content_type_valid": content_type_valid,
                "header_bytes": header_bytes,
                "body_bytes": len(body),
                "declared_body_bytes": content_length,
                "body_base64": base64.b64encode(body).decode("ascii"),
                "body_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
                "body_truncated": body_truncated,
                "event_valid": event_valid,
                "accepted": accepted,
                "nonce": nonce,
                "event": event,
                "data": data,
                "response_status": status,
            }
        )
        self._respond(status if recorded else 429)

    def _respond(self, status: int) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
        except OSError:
            pass


def _write_ready(path: Path, port: int) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"port": port}, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--credential", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()

    config = _read_json(args.config, MAX_CONFIG_BYTES)
    with args.credential.open("rb") as stream:
        credential = stream.read(MAX_CREDENTIAL_BYTES + 1)
    if len(credential) > MAX_CREDENTIAL_BYTES:
        raise ValueError("credential exceeded its bound")
    token = credential.decode("ascii")
    args.state_dir.mkdir(parents=True, exist_ok=True)
    state = EventLedgerState(config, token, args.state_dir)
    server = EventLedgerServer((args.host, args.port), state)
    stopping = False

    def request_stop(signum: int, frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    server.timeout = 0.2
    _write_ready(args.state_dir / "ready.json", server.server_address[1])
    try:
        while not stopping:
            server.handle_request()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
