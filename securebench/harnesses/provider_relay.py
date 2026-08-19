"""Credential-injecting provider relay for named agent harnesses."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import socketserver
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
MAX_PROVIDER_REQUEST_BYTES = 16 * 1024 * 1024
MAX_RELAY_LOG_BYTES = 4 * 1024 * 1024
UNINSPECTABLE_TOOL_REQUEST = "securebench.uninspectable_request"
_LOG_LOCK = threading.Lock()


@dataclass(frozen=True)
class RelayConfig:
    provider: str
    upstream_host: str
    credential: str | None
    credential_kind: str
    allow_external_tools: bool
    log_dir: Path
    allowed_client_tool_types: tuple[str, ...] = ()
    allow_untyped_client_tools: bool = False
    credential_file: Path | None = None
    allowed_path_prefixes: tuple[str, ...] = ()
    allowed_methods: tuple[str, ...] = ("POST",)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    config = relay_config_from_env()

    class Handler(ProviderRelayHandler):
        relay_config = config

    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        server.serve_forever()
    return 0


def relay_config_from_env() -> RelayConfig:
    provider = os.environ.get("SECUREBENCH_PROVIDER", "").strip().lower()
    if provider not in {"openai", "anthropic"}:
        raise SystemExit("SECUREBENCH_PROVIDER must be 'openai' or 'anthropic'")
    host = required_env("SECUREBENCH_UPSTREAM_HOST")
    credential_kind = required_env("SECUREBENCH_CREDENTIAL_KIND")
    credential: str | None = None
    credential_file: Path | None = None
    if credential_kind == "codex-oauth":
        credential_file = Path(required_env("SECUREBENCH_CREDENTIAL_FILE"))
        if not credential_file.is_file():
            raise SystemExit(f"Codex OAuth credential file does not exist: {credential_file}")
    elif credential_kind in {"bearer", "x-api-key"}:
        credential_env = required_env("SECUREBENCH_CREDENTIAL_ENV")
        credential = os.environ.get(credential_env)
        if not credential:
            raise SystemExit(f"{credential_env} is required")
    else:
        raise SystemExit(
            "SECUREBENCH_CREDENTIAL_KIND must be 'bearer', 'x-api-key', or 'codex-oauth'"
        )
    allow_external_tools = os.environ.get("SECUREBENCH_ALLOW_EXTERNAL_TOOLS", "").lower() == "true"
    log_dir = Path(os.environ.get("SECUREBENCH_RELAY_LOG_DIR", "/tmp/securebench-provider-relay"))
    log_dir.mkdir(parents=True, exist_ok=True)
    return RelayConfig(
        provider=provider,
        upstream_host=host,
        credential=credential,
        credential_kind=credential_kind,
        allowed_client_tool_types=string_tuple_env("SECUREBENCH_ALLOWED_CLIENT_TOOL_TYPES"),
        allow_untyped_client_tools=(
            os.environ.get("SECUREBENCH_ALLOW_UNTYPED_CLIENT_TOOLS", "").lower()
            == "true"
        ),
        allow_external_tools=allow_external_tools,
        log_dir=log_dir,
        credential_file=credential_file,
        allowed_path_prefixes=string_tuple_env("SECUREBENCH_ALLOWED_PATH_PREFIXES"),
        allowed_methods=string_tuple_env("SECUREBENCH_ALLOWED_METHODS") or ("POST",),
    )


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def string_tuple_env(name: str) -> tuple[str, ...]:
    value = os.environ.get(name, "[]")
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{name} must be a JSON string array") from exc
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise SystemExit(f"{name} must be a JSON string array")
    return tuple(item for item in loaded if item)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class ProviderRelayHandler(BaseHTTPRequestHandler):
    relay_config: RelayConfig
    timeout = 600

    def do_GET(self) -> None:
        self._relay()

    def do_HEAD(self) -> None:
        self._relay()

    def do_POST(self) -> None:
        self._relay()

    def do_PUT(self) -> None:
        self._relay()

    def do_PATCH(self) -> None:
        self._relay()

    def do_DELETE(self) -> None:
        self._relay()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _relay(self) -> None:
        if self.command not in self.relay_config.allowed_methods:
            self._send_request_block("upstream_method", status=403)
            return
        if not path_allowed(self.path, self.relay_config.allowed_path_prefixes):
            self._send_path_block()
            return
        if self.headers.get("Transfer-Encoding") is not None:
            self._send_request_block("unsupported_transfer_encoding", status=400)
            return
        content_lengths = self.headers.get_all("Content-Length", [])
        if len(content_lengths) > 1:
            self._send_request_block("ambiguous_content_length", status=400)
            return
        content_length = content_lengths[0] if content_lengths else None
        body = b""
        if content_length is not None:
            try:
                remaining = int(content_length)
            except ValueError:
                self.send_error(400)
                return
            if remaining < 0:
                self.send_error(400)
                return
            if remaining > MAX_PROVIDER_REQUEST_BYTES:
                self._send_request_block("request_too_large", status=413)
                return
            body = self.rfile.read(remaining)
            if len(body) != remaining:
                self._send_request_block("incomplete_request", status=400)
                return

        blocked_tools = blocked_external_tools(
            body,
            self.relay_config.allow_external_tools,
            allowed_client_tool_types=self.relay_config.allowed_client_tool_types,
            allow_untyped_client_tools=self.relay_config.allow_untyped_client_tools,
        )
        if blocked_tools:
            self._send_policy_block(blocked_tools, len(body))
            return

        response_status = 502
        response_bytes = 0
        upstream = None
        try:
            response = None
            attempts = 2 if self.relay_config.credential_kind == "codex-oauth" else 1
            for attempt in range(attempts):
                upstream = http.client.HTTPSConnection(
                    self.relay_config.upstream_host,
                    443,
                    timeout=self.timeout,
                )
                headers = upstream_headers(
                    self.relay_config,
                    self.headers,
                    force_oauth_refresh=attempt > 0,
                )
                upstream.request(self.command, self.path, body=body, headers=headers)
                response = upstream.getresponse()
                if response.status != 401 or attempt + 1 == attempts:
                    break
                response.read()
                upstream.close()
                upstream = None
            if response is None:
                raise OSError("provider relay received no upstream response")
            response_status = response.status
            self.send_response(response.status, response.reason)
            response_headers = response.getheaders()
            connection_headers = {
                token.strip().lower()
                for name, value in response_headers
                if name.lower() == "connection"
                for token in value.split(",")
                if token.strip()
            }
            for name, value in response_headers:
                if (
                    name.lower() in HOP_BY_HOP_HEADERS
                    or name.lower() in connection_headers
                ):
                    continue
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    response_bytes += len(chunk)
                    self.wfile.write(chunk)
        except (OSError, http.client.HTTPException):
            self.send_error(502)
        finally:
            if upstream is not None:
                try:
                    upstream.close()
                except Exception:
                    pass
            write_decision(
                self.relay_config,
                {
                    "provider": self.relay_config.provider,
                    "path": self.path,
                    "status": "forwarded",
                    "response_code": response_status,
                    "request_bytes": len(body),
                    "response_bytes": response_bytes,
                    "blocked_tools": [],
                },
            )

    def _send_policy_block(self, blocked_tools: tuple[str, ...], request_bytes: int) -> None:
        payload = provider_error_payload(self.relay_config.provider, blocked_tools)
        content = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)
        write_decision(
            self.relay_config,
            {
                "provider": self.relay_config.provider,
                "path": self.path,
                "status": "blocked",
                "response_code": 403,
                "request_bytes": request_bytes,
                "response_bytes": len(content),
                "blocked_tools": list(blocked_tools),
            },
        )

    def _send_request_block(self, reason: str, *, status: int) -> None:
        self.send_error(status)
        write_decision(
            self.relay_config,
            {
                "provider": self.relay_config.provider,
                "path": self.path,
                "status": "blocked",
                "response_code": status,
                "request_bytes": 0,
                "response_bytes": 0,
                "blocked_tools": [],
                "blocked_reason": reason,
            },
        )

    def _send_path_block(self) -> None:
        content = json.dumps(
            {
                "error": {
                    "message": "SecureBench provider relay blocked this upstream path",
                    "type": "securebench_policy_error",
                }
            },
            sort_keys=True,
        ).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)
        write_decision(
            self.relay_config,
            {
                "provider": self.relay_config.provider,
                "path": self.path,
                "status": "blocked",
                "response_code": 403,
                "request_bytes": 0,
                "response_bytes": len(content),
                "blocked_tools": [],
                "blocked_reason": "upstream_path",
            },
        )


def upstream_headers(
    config: RelayConfig,
    headers: Any,
    *,
    force_oauth_refresh: bool = False,
) -> dict[str, str]:
    result: dict[str, str] = {}
    connection_headers = {
        token.strip().lower()
        for value in headers.get_all("Connection", [])
        for token in value.split(",")
        if token.strip()
    }
    for name, value in headers.items():
        lower = name.lower()
        if lower in HOP_BY_HOP_HEADERS or lower in connection_headers or lower in {
            "host",
            "authorization",
            "content-length",
            "x-api-key",
            "chatgpt-account-id",
        }:
            continue
        result[name] = value
    result["Host"] = config.upstream_host
    if config.credential_kind == "bearer":
        if config.credential is None:
            raise OSError("provider relay bearer credential is unavailable")
        result["Authorization"] = f"Bearer {config.credential}"
    elif config.credential_kind == "x-api-key":
        if config.credential is None:
            raise OSError("provider relay API key is unavailable")
        result["x-api-key"] = config.credential
    elif config.credential_kind == "codex-oauth":
        if config.credential_file is None:
            raise OSError("provider relay Codex OAuth credential file is unavailable")
        credentials = _codex_oauth_credentials(
            config.credential_file,
            force_refresh=force_oauth_refresh,
        )
        result["Authorization"] = f"Bearer {credentials.access_token}"
        result["ChatGPT-Account-Id"] = credentials.account_id
    else:
        raise OSError(f"unsupported provider relay credential kind: {config.credential_kind}")
    return result


def path_allowed(path: str, allowed_prefixes: tuple[str, ...]) -> bool:
    if not allowed_prefixes:
        return True
    request_path = path.split("?", 1)[0]
    if (
        not request_path.startswith("/")
        or "%" in request_path
        or "\\" in request_path
        or "#" in request_path
        or "//" in request_path
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in request_path)
    ):
        return False
    if any(segment in {".", ".."} for segment in request_path.split("/")):
        return False
    return any(
        request_path.startswith(prefix)
        if prefix.endswith("/")
        else request_path == prefix or request_path.startswith(prefix + "/")
        for prefix in allowed_prefixes
    )


def _codex_oauth_credentials(path: Path, *, force_refresh: bool = False) -> Any:
    try:
        from codex_oauth import ensure_valid_codex_oauth_credentials
    except ImportError:
        from securebench.harnesses.codex_oauth import ensure_valid_codex_oauth_credentials
    return ensure_valid_codex_oauth_credentials(path, force_refresh=force_refresh)


def blocked_external_tools(
    body: bytes,
    allow_external_tools: bool,
    *,
    allowed_client_tool_types: tuple[str, ...] = (),
    allow_untyped_client_tools: bool = False,
) -> tuple[str, ...]:
    if allow_external_tools or not body:
        return ()
    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        return (UNINSPECTABLE_TOOL_REQUEST,)
    if not isinstance(payload, dict):
        return (UNINSPECTABLE_TOOL_REQUEST,)
    tools = payload.get("tools")
    if tools is None:
        return ()
    if not isinstance(tools, list):
        return (UNINSPECTABLE_TOOL_REQUEST,)
    blocked = []
    for tool in tools:
        tool_type = _tool_type(tool)
        if tool_type is None:
            if allow_untyped_client_tools and _valid_untyped_client_tool(tool):
                continue
            blocked.append(UNINSPECTABLE_TOOL_REQUEST)
            continue
        if tool_type not in allowed_client_tool_types:
            blocked.append(tool_type)
    return tuple(dict.fromkeys(blocked))


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _tool_type(tool: Any) -> str | None:
    if not isinstance(tool, dict):
        return None
    value = tool.get("type")
    if isinstance(value, str) and value:
        return value
    return None


def _valid_untyped_client_tool(tool: Any) -> bool:
    return (
        isinstance(tool, dict)
        and isinstance(tool.get("name"), str)
        and bool(tool["name"])
        and isinstance(tool.get("input_schema"), dict)
    )


def provider_error_payload(provider: str, blocked_tools: tuple[str, ...]) -> dict[str, Any]:
    message = "SecureBench provider relay blocked external provider-hosted tool(s): "
    message += ", ".join(blocked_tools)
    if provider == "anthropic":
        return {
            "type": "error",
            "error": {
                "type": "permission_error",
                "message": message,
            },
        }
    return {
        "error": {
            "message": message,
            "type": "permission_error",
            "param": "tools",
            "code": "external_tools_blocked",
        }
    }


def write_decision(config: RelayConfig, record: dict[str, Any]) -> None:
    safe_record = {
        **record,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    encoded = (json.dumps(safe_record, sort_keys=True) + "\n").encode("utf-8")
    path = config.log_dir / "decisions.jsonl"
    with _LOG_LOCK:
        with path.open("ab") as handle:
            if handle.tell() + len(encoded) <= MAX_RELAY_LOG_BYTES:
                handle.write(encoded)


if __name__ == "__main__":
    raise SystemExit(main())
