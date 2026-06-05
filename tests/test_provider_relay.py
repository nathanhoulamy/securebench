import io
import json
from email.message import Message

from securebench.harnesses import provider_relay
from securebench.harnesses.claude_code import CLAUDE_CODE_PROVIDER_RELAY_SPEC
from securebench.harnesses.codex import CODEX_PROVIDER_RELAY_SPEC
from securebench.harnesses.provider_relay import (
    RelayConfig,
    ProviderRelayHandler,
    blocked_external_tools,
    upstream_headers,
)


def headers(**items):
    message = Message()
    for name, value in items.items():
        message[name.replace("_", "-")] = value
    return message


def test_openai_relay_injects_real_auth_and_strips_dummy_auth(tmp_path):
    config = RelayConfig(
        provider="openai",
        upstream_host="api.openai.com",
        api_key="real-key",
        blocked_tool_types=CODEX_PROVIDER_RELAY_SPEC.blocked_tool_types,
        blocked_tool_prefixes=CODEX_PROVIDER_RELAY_SPEC.blocked_tool_prefixes,
        allowed_client_tool_types=CODEX_PROVIDER_RELAY_SPEC.allowed_client_tool_types,
        allow_external_tools=False,
        log_dir=tmp_path,
    )

    result = upstream_headers(
        config,
        headers(
            Host="securebench-provider-relay",
            Authorization="Bearer dummy",
            X_API_Key="dummy",
            Content_Type="application/json",
        ),
    )

    assert result["Authorization"] == "Bearer real-key"
    assert result["Content-Type"] == "application/json"
    assert "x-api-key" not in {name.lower() for name in result}
    assert result["Host"] == "api.openai.com"


def test_anthropic_relay_injects_real_api_key(tmp_path):
    config = RelayConfig(
        provider="anthropic",
        upstream_host="api.anthropic.com",
        api_key="real-key",
        blocked_tool_types=CLAUDE_CODE_PROVIDER_RELAY_SPEC.blocked_tool_types,
        blocked_tool_prefixes=CLAUDE_CODE_PROVIDER_RELAY_SPEC.blocked_tool_prefixes,
        allowed_client_tool_types=CLAUDE_CODE_PROVIDER_RELAY_SPEC.allowed_client_tool_types,
        allow_external_tools=False,
        log_dir=tmp_path,
    )

    result = upstream_headers(
        config,
        headers(
            Host="securebench-provider-relay",
            Authorization="Bearer dummy",
            X_API_Key="dummy",
            Anthropic_Version="2023-06-01",
        ),
    )

    lower = {name.lower(): value for name, value in result.items()}
    assert lower["x-api-key"] == "real-key"
    assert lower["anthropic-version"] == "2023-06-01"
    assert "authorization" not in {name.lower() for name in result}
    assert result["Host"] == "api.anthropic.com"


def test_openai_policy_blocks_hosted_tools_and_allows_client_tools():
    blocked = blocked_external_tools(
        "application/json",
        json.dumps(
            {
                "tools": [
                    {"type": "function", "name": "local_tool"},
                    {"type": "custom", "name": "custom_tool"},
                    {"type": "web_search"},
                    {"type": "web_search_preview"},
                    {"type": "web_search_2025_08_26"},
                    {"type": "computer_use_preview"},
                    {"type": "mcp"},
                ]
            }
        ).encode(),
        allow_external_tools=False,
        blocked_tool_types=CODEX_PROVIDER_RELAY_SPEC.blocked_tool_types,
        blocked_tool_prefixes=CODEX_PROVIDER_RELAY_SPEC.blocked_tool_prefixes,
        allowed_client_tool_types=CODEX_PROVIDER_RELAY_SPEC.allowed_client_tool_types,
    )

    assert blocked == (
        "web_search",
        "web_search_preview",
        "web_search_2025_08_26",
        "computer_use_preview",
        "mcp",
    )


def test_anthropic_policy_blocks_server_tools_and_allows_client_tools():
    blocked = blocked_external_tools(
        "application/json",
        json.dumps(
            {
                "tools": [
                    {"name": "read_file", "description": "local", "input_schema": {"type": "object"}},
                    {"type": "web_search_20250305", "name": "web_search"},
                    {"type": "web_fetch_20250910", "name": "web_fetch"},
                ]
            }
        ).encode(),
        allow_external_tools=False,
        blocked_tool_types=CLAUDE_CODE_PROVIDER_RELAY_SPEC.blocked_tool_types,
        blocked_tool_prefixes=CLAUDE_CODE_PROVIDER_RELAY_SPEC.blocked_tool_prefixes,
        allowed_client_tool_types=CLAUDE_CODE_PROVIDER_RELAY_SPEC.allowed_client_tool_types,
    )

    assert blocked == ("web_search_20250305", "web_fetch_20250910")


def test_policy_allows_external_tools_when_enabled():
    blocked = blocked_external_tools(
        "application/json",
        b'{"tools": [{"type": "web_search"}]}',
        allow_external_tools=True,
        blocked_tool_types=CODEX_PROVIDER_RELAY_SPEC.blocked_tool_types,
        blocked_tool_prefixes=CODEX_PROVIDER_RELAY_SPEC.blocked_tool_prefixes,
        allowed_client_tool_types=CODEX_PROVIDER_RELAY_SPEC.allowed_client_tool_types,
    )

    assert blocked == ()


def test_handler_forwards_streaming_chunks_and_logs_redacted_decision(monkeypatch, tmp_path):
    chunks = [b"data: one\n\n", b"data: two\n\n", b""]
    sent_request = {}

    class FakeResponse:
        status = 200
        reason = "OK"

        def getheaders(self):
            return [("Content-Type", "text/event-stream")]

        def read(self, size):
            return chunks.pop(0)

    class FakeConnection:
        def __init__(self, host, port, timeout):
            sent_request["connect"] = (host, port, timeout)

        def request(self, method, path, body=None, headers=None):
            sent_request["request"] = (method, path, body, headers)

        def getresponse(self):
            return FakeResponse()

        def close(self):
            sent_request["closed"] = True

    monkeypatch.setattr(provider_relay.http.client, "HTTPSConnection", FakeConnection)

    handler = object.__new__(ProviderRelayHandler)
    handler.relay_config = RelayConfig(
        provider="openai",
        upstream_host="api.openai.com",
        api_key="real-key",
        blocked_tool_types=CODEX_PROVIDER_RELAY_SPEC.blocked_tool_types,
        blocked_tool_prefixes=CODEX_PROVIDER_RELAY_SPEC.blocked_tool_prefixes,
        allowed_client_tool_types=CODEX_PROVIDER_RELAY_SPEC.allowed_client_tool_types,
        allow_external_tools=False,
        log_dir=tmp_path,
    )
    handler.command = "POST"
    handler.path = "/v1/responses"
    handler.headers = headers(Content_Type="application/json", Content_Length="2")
    handler.rfile = io.BytesIO(b"{}")
    handler.wfile = io.BytesIO()
    handler.timeout = 7
    sent_status = []
    sent_headers = []
    handler.send_response = lambda status, reason=None: sent_status.append((status, reason))
    handler.send_header = lambda name, value: sent_headers.append((name, value))
    handler.end_headers = lambda: None
    handler.send_error = lambda status: sent_status.append((status, None))

    handler._relay()

    assert sent_request["connect"] == ("api.openai.com", 443, 7)
    assert sent_request["request"][0:3] == ("POST", "/v1/responses", b"{}")
    assert sent_request["request"][3]["Authorization"] == "Bearer real-key"
    assert handler.wfile.getvalue() == b"data: one\n\ndata: two\n\n"
    assert sent_status == [(200, "OK")]
    assert ("Content-Type", "text/event-stream") in sent_headers
    records = [
        json.loads(line)
        for line in (tmp_path / "decisions.jsonl").read_text().splitlines()
    ]
    assert records == [
        {
            "blocked_tool_types": [],
            "path": "/v1/responses",
            "provider": "openai",
            "request_bytes": 2,
            "response_bytes": 22,
            "response_code": 200,
            "status": "forwarded",
            "timestamp": records[0]["timestamp"],
        }
    ]
    assert "real-key" not in (tmp_path / "decisions.jsonl").read_text()
