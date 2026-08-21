"""Bounded data-plane server for ``securebench.http-request-recorder/v1``.

This module deliberately uses only the Python standard library so the reviewed
server can run from a read-only bind mount in a small, digest-pinned image.
The evidence directory is the only writable host mount and is never exposed to
the Evaluation participant.
"""

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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


MAX_CONFIG_BYTES = 256 * 1024
MAX_CREDENTIAL_BYTES = 512
MAX_REQUEST_TARGET_BYTES = 8192
HTTP_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def _read_json(path: Path, maximum_bytes: int) -> Any:
    with path.open("rb") as stream:
        content = stream.read(maximum_bytes + 1)
    if len(content) > maximum_bytes:
        raise ValueError("configuration exceeded its bound")
    return json.loads(content)


class RecorderState:
    def __init__(self, config: dict[str, Any], token: str, state_dir: Path) -> None:
        self.challenge_id = config["challenge_id"]
        self.evaluation_id = config["evaluation_id"]
        self.path = config["settings"].get("path", "/")
        self.response_status = config["settings"].get("response_status", 204)
        self.response_body = config["settings"].get("response_body", "").encode("utf-8")
        self.max_requests = config["limits"]["max_requests"]
        self.max_body_bytes = config["limits"]["max_body_bytes"]
        self.max_header_bytes = config["limits"].get("max_header_bytes", 32768)
        self.token = token
        self.state_dir = state_dir
        self.records_path = state_dir / "requests.jsonl"
        self.truncated_path = state_dir / "truncated.flag"
        self.sequence = 0
        self.lock = threading.Lock()

    def mark_truncated(self) -> None:
        self.truncated_path.touch(exist_ok=True)

    def at_capacity(self) -> bool:
        with self.lock:
            return self.sequence >= self.max_requests

    def append(self, record: dict[str, Any]) -> bool:
        with self.lock:
            if self.sequence >= self.max_requests:
                self.truncated_path.touch(exist_ok=True)
                return False
            record["sequence"] = self.sequence
            self.sequence += 1
            encoded = json.dumps(
                record,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            with self.records_path.open("ab", buffering=0) as stream:
                stream.write(encoded)
                os.fsync(stream.fileno())
        return True


class RecorderServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: RecorderState) -> None:
        super().__init__(address, RecorderHandler)
        self.recorder_state = state

    def handle_error(self, request: object, client_address: object) -> None:
        # Candidate-controlled disconnects and malformed sockets must not
        # generate unbounded tracebacks in the container log.
        return


class RecorderHandler(BaseHTTPRequestHandler):
    server: RecorderServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_request()

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_request()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_request()

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_request()

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_request()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_request()

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib callback name
        self._record_request()

    def log_message(self, format: str, *args: object) -> None:
        # Candidate-controlled request data must not reach host logs.
        return

    def _record_request(self) -> None:
        state = self.server.recorder_state
        self.close_connection = True
        if state.at_capacity():
            state.mark_truncated()
            self._respond(429, b"")
            return
        target_bytes = self.path.encode("utf-8", errors="replace")
        target_too_large = len(target_bytes) > MAX_REQUEST_TARGET_BYTES
        target = target_bytes[:MAX_REQUEST_TARGET_BYTES].decode("utf-8", errors="ignore")
        target_invalid = "\\" in target or "#" in target or any(
            ord(character) < 0x21 or ord(character) > 0x7E for character in target
        )
        authorizations = self.headers.get_all("Authorization", [])
        authenticated = len(authorizations) == 1 and hmac.compare_digest(
            authorizations[0], f"Bearer {state.token}"
        )
        header_bytes = sum(
            len(name.encode("utf-8", errors="replace"))
            + len(value.encode("utf-8", errors="replace"))
            + 4
            for name, value in self.headers.items()
        )
        headers: list[dict[str, str]] = []
        retained_header_bytes = 0
        header_truncated = False
        for name, value in self.headers.items():
            normalized_name = name.lower()
            if normalized_name in {"authorization", "proxy-authorization"}:
                continue
            name_bytes = normalized_name.encode("utf-8", errors="replace")
            value_bytes = value.encode("utf-8", errors="replace")
            item_bytes = len(name_bytes) + len(value_bytes) + 4
            if (
                HTTP_HEADER_NAME.fullmatch(name) is None
                or any(
                    (ord(character) < 0x20 and character != "\t")
                    or ord(character) == 0x7F
                    for character in value
                )
                or len(name_bytes) > 256
                or len(value_bytes) > state.max_header_bytes
                or retained_header_bytes + item_bytes > state.max_header_bytes
                or len(headers) >= 128
            ):
                header_truncated = True
                continue
            retained_header_bytes += item_bytes
            headers.append({"name": normalized_name, "value": value})
        transfer_encodings = self.headers.get_all("Transfer-Encoding", [])
        content_lengths = self.headers.get_all("Content-Length", [])
        content_length_value = content_lengths[0] if len(content_lengths) == 1 else "0"
        try:
            content_length = int(content_length_value)
            if content_length < 0:
                raise ValueError
        except ValueError:
            content_length = 0
            invalid_length = True
        else:
            invalid_length = len(content_lengths) > 1

        body_truncated = content_length > state.max_body_bytes
        read_length = min(content_length, state.max_body_bytes)
        body = self.rfile.read(read_length) if read_length else b""
        if len(body) != read_length:
            body_truncated = True

        try:
            request_path = urlsplit(target).path
        except ValueError:
            request_path = ""
        origin_form = target.startswith("/") and not target.startswith("//")
        path_matched = origin_form and not target_invalid and request_path == state.path

        if target_too_large:
            status, response_body = 414, b""
            state.mark_truncated()
        elif target_invalid:
            status, response_body = 400, b""
        elif header_bytes > state.max_header_bytes or header_truncated:
            status, response_body = 431, b""
            header_truncated = True
            state.mark_truncated()
        elif transfer_encodings or invalid_length:
            status, response_body = 400, b""
            body_truncated = True
            state.mark_truncated()
        elif body_truncated:
            status, response_body = 413, b""
            state.mark_truncated()
        elif not authenticated:
            status, response_body = 401, b""
        elif not path_matched:
            status, response_body = 404, b""
        else:
            status, response_body = state.response_status, state.response_body

        recorded = state.append(
            {
                "challenge_id": state.challenge_id,
                "evaluation_id": state.evaluation_id,
                "method": self.command,
                "target": target,
                "target_truncated": target_too_large,
                "headers": headers,
                "header_bytes": header_bytes,
                "headers_truncated": header_truncated,
                "body_base64": base64.b64encode(body).decode("ascii"),
                "body_bytes": len(body),
                "declared_body_bytes": content_length,
                "body_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
                "body_truncated": body_truncated,
                "authenticated": authenticated,
                "path_matched": path_matched,
                "response_status": status,
            }
        )
        self._respond(status if recorded else 429, response_body if recorded else b"")

    def _respond(self, status: int, body: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD" and body:
                self.wfile.write(body)
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
    state = RecorderState(config, token, args.state_dir)
    server = RecorderServer((args.host, args.port), state)
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
