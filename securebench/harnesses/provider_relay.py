"""Credential-injecting provider relay for named agent harnesses."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import socketserver
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


@dataclass(frozen=True)
class RelayConfig:
    provider: str
    upstream_host: str
    credential: str
    credential_kind: str
    blocked_tool_types: tuple[str, ...]
    blocked_tool_prefixes: tuple[str, ...]
    allowed_client_tool_types: tuple[str, ...]
    allow_external_tools: bool
    log_dir: Path


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
    credential_env = required_env("SECUREBENCH_CREDENTIAL_ENV")
    credential = os.environ.get(credential_env)
    if not credential:
        raise SystemExit(f"{credential_env} is required")
    credential_kind = required_env("SECUREBENCH_CREDENTIAL_KIND")
    if credential_kind not in {"bearer", "x-api-key"}:
        raise SystemExit("SECUREBENCH_CREDENTIAL_KIND must be 'bearer' or 'x-api-key'")
    allow_external_tools = os.environ.get("SECUREBENCH_ALLOW_EXTERNAL_TOOLS", "").lower() == "true"
    log_dir = Path(os.environ.get("SECUREBENCH_RELAY_LOG_DIR", "/tmp/securebench-provider-relay"))
    log_dir.mkdir(parents=True, exist_ok=True)
    return RelayConfig(
        provider=provider,
        upstream_host=host,
        credential=credential,
        credential_kind=credential_kind,
        blocked_tool_types=string_tuple_env("SECUREBENCH_BLOCKED_TOOL_TYPES"),
        blocked_tool_prefixes=string_tuple_env("SECUREBENCH_BLOCKED_TOOL_PREFIXES"),
        allowed_client_tool_types=string_tuple_env("SECUREBENCH_ALLOWED_CLIENT_TOOL_TYPES"),
        allow_external_tools=allow_external_tools,
        log_dir=log_dir,
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
        content_length = self.headers.get("Content-Length")
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
            body = self.rfile.read(remaining)

        blocked_tools = blocked_external_tools(
            self.headers.get("Content-Type", ""),
            body,
            self.relay_config.allow_external_tools,
            blocked_tool_types=self.relay_config.blocked_tool_types,
            blocked_tool_prefixes=self.relay_config.blocked_tool_prefixes,
            allowed_client_tool_types=self.relay_config.allowed_client_tool_types,
        )
        if blocked_tools:
            self._send_policy_block(blocked_tools, len(body))
            return

        response_status = 502
        response_bytes = 0
        upstream = None
        try:
            upstream = http.client.HTTPSConnection(
                self.relay_config.upstream_host,
                443,
                timeout=self.timeout,
            )
            headers = upstream_headers(self.relay_config, self.headers)
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            response_status = response.status
            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                if name.lower() in HOP_BY_HOP_HEADERS:
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
        except OSError:
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
                    "blocked_tool_types": [],
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
                "blocked_tool_types": list(blocked_tools),
            },
        )


def upstream_headers(config: RelayConfig, headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in headers.items():
        lower = name.lower()
        if lower in HOP_BY_HOP_HEADERS or lower in {"host", "authorization", "x-api-key"}:
            continue
        result[name] = value
    result["Host"] = config.upstream_host
    if config.credential_kind == "bearer":
        result["Authorization"] = f"Bearer {config.credential}"
    else:
        result["x-api-key"] = config.credential
    return result


def blocked_external_tools(
    content_type: str,
    body: bytes,
    allow_external_tools: bool,
    *,
    blocked_tool_types: tuple[str, ...],
    blocked_tool_prefixes: tuple[str, ...],
    allowed_client_tool_types: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if allow_external_tools or not body or "json" not in content_type.lower():
        return ()
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, dict):
        return ()
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return ()
    blocked = []
    for tool in tools:
        tool_type = _tool_type(tool)
        if tool_type is None:
            continue
        if is_blocked_tool(
            tool_type,
            blocked_tool_types=blocked_tool_types,
            blocked_tool_prefixes=blocked_tool_prefixes,
            allowed_client_tool_types=allowed_client_tool_types,
        ):
            blocked.append(tool_type)
    return tuple(dict.fromkeys(blocked))


def _tool_type(tool: Any) -> str | None:
    if not isinstance(tool, dict):
        return None
    value = tool.get("type")
    if isinstance(value, str) and value:
        return value
    return None


def is_blocked_tool(
    tool_type: str,
    *,
    blocked_tool_types: tuple[str, ...],
    blocked_tool_prefixes: tuple[str, ...],
    allowed_client_tool_types: tuple[str, ...] = (),
) -> bool:
    if tool_type in allowed_client_tool_types:
        return False
    return tool_type in blocked_tool_types or tool_type.startswith(blocked_tool_prefixes)


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
    path = config.log_dir / "decisions.jsonl"
    with path.open("a") as handle:
        handle.write(json.dumps(safe_record, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
