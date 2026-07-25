import io
import json
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

from securebench.harnesses import provider_relay
from securebench.harnesses.claude_code import (
    CLAUDE_CODE_PROVIDER_RELAY_SPEC,
    CLAUDE_CODE_SUBSCRIPTION_RELAY_SPEC,
)
from securebench.harnesses.codex import (
    CODEX_PROVIDER_RELAY_SPEC,
    CODEX_SUBSCRIPTION_RELAY_SPEC,
)
from securebench.harnesses.provider_relay import (
    RelayConfig,
    ProviderRelayHandler,
    blocked_external_tools,
    relay_config_from_env,
    path_allowed,
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
        credential="real-key",
        credential_kind="bearer",
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
        credential="real-key",
        credential_kind="x-api-key",
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


def test_anthropic_relay_injects_subscription_bearer_token(tmp_path):
    config = RelayConfig(
        provider="anthropic",
        upstream_host="api.anthropic.com",
        credential="real-oauth-token",
        credential_kind="bearer",
        blocked_tool_types=CLAUDE_CODE_SUBSCRIPTION_RELAY_SPEC.blocked_tool_types,
        blocked_tool_prefixes=CLAUDE_CODE_SUBSCRIPTION_RELAY_SPEC.blocked_tool_prefixes,
        allowed_client_tool_types=CLAUDE_CODE_SUBSCRIPTION_RELAY_SPEC.allowed_client_tool_types,
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
    assert lower["authorization"] == "Bearer real-oauth-token"
    assert lower["anthropic-version"] == "2023-06-01"
    assert "x-api-key" not in lower
    assert result["Host"] == "api.anthropic.com"


def test_relay_config_from_env_reads_generic_credential(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SECUREBENCH_PROVIDER", "anthropic")
    monkeypatch.setenv("SECUREBENCH_UPSTREAM_HOST", "api.anthropic.com")
    monkeypatch.setenv("SECUREBENCH_CREDENTIAL_ENV", "CLAUDE_CODE_OAUTH_TOKEN")
    monkeypatch.setenv("SECUREBENCH_CREDENTIAL_KIND", "bearer")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "real-oauth-token")
    monkeypatch.setenv("SECUREBENCH_RELAY_LOG_DIR", str(tmp_path))

    config = relay_config_from_env()

    assert config.provider == "anthropic"
    assert config.upstream_host == "api.anthropic.com"
    assert config.credential == "real-oauth-token"
    assert config.credential_kind == "bearer"
    assert config.log_dir == tmp_path


def test_relay_config_from_env_reads_codex_oauth_file(monkeypatch, tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{}")
    monkeypatch.setenv("SECUREBENCH_PROVIDER", "openai")
    monkeypatch.setenv("SECUREBENCH_UPSTREAM_HOST", "chatgpt.com")
    monkeypatch.setenv("SECUREBENCH_CREDENTIAL_KIND", "codex-oauth")
    monkeypatch.setenv("SECUREBENCH_CREDENTIAL_FILE", str(auth_path))
    monkeypatch.setenv(
        "SECUREBENCH_ALLOWED_PATH_PREFIXES",
        '["/backend-api/codex/"]',
    )
    monkeypatch.setenv("SECUREBENCH_RELAY_LOG_DIR", str(tmp_path))

    config = relay_config_from_env()

    assert config.credential is None
    assert config.credential_file == auth_path
    assert config.allowed_path_prefixes == ("/backend-api/codex/",)


def test_codex_subscription_relay_refreshes_auth_outside_agent(
    monkeypatch,
    tmp_path,
):
    auth_path = tmp_path / "auth.json"
    config = RelayConfig(
        provider="openai",
        upstream_host="chatgpt.com",
        credential=None,
        credential_kind="codex-oauth",
        blocked_tool_types=CODEX_SUBSCRIPTION_RELAY_SPEC.blocked_tool_types,
        blocked_tool_prefixes=CODEX_SUBSCRIPTION_RELAY_SPEC.blocked_tool_prefixes,
        allowed_client_tool_types=CODEX_SUBSCRIPTION_RELAY_SPEC.allowed_client_tool_types,
        allow_external_tools=False,
        log_dir=tmp_path,
        credential_file=auth_path,
        allowed_path_prefixes=CODEX_SUBSCRIPTION_RELAY_SPEC.allowed_path_prefixes,
    )
    seen = {}

    def fake_credentials(path, *, force_refresh=False):
        seen["path"] = path
        seen["force_refresh"] = force_refresh
        return SimpleNamespace(access_token="real-access", account_id="real-account")

    monkeypatch.setattr(provider_relay, "_codex_oauth_credentials", fake_credentials)

    result = upstream_headers(
        config,
        headers(
            Authorization="Bearer dummy",
            ChatGPT_Account_Id="dummy-account",
            Content_Type="application/json",
        ),
    )

    assert seen == {"path": auth_path, "force_refresh": False}
    assert result["Authorization"] == "Bearer real-access"
    assert result["ChatGPT-Account-Id"] == "real-account"
    assert "dummy-account" not in result.values()


def test_codex_subscription_relay_limits_chatgpt_backend_paths():
    prefixes = CODEX_SUBSCRIPTION_RELAY_SPEC.allowed_path_prefixes

    assert path_allowed("/backend-api/codex/responses", prefixes) is True
    assert path_allowed("/backend-api/codex/models?client_version=1", prefixes) is True
    assert path_allowed("/backend-api/me", prefixes) is False
    assert path_allowed("/backend-api/codex-evil", prefixes) is False
    assert path_allowed("/backend-api/codex/../me", prefixes) is False
    assert path_allowed("/backend-api/codex/%2e%2e/me", prefixes) is False
    assert path_allowed("/backend-api/codex//responses", prefixes) is False
    assert path_allowed(r"/backend-api/codex/\..\me", prefixes) is False


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
        credential="real-key",
        credential_kind="bearer",
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


def test_handler_refreshes_codex_oauth_once_after_unauthorized(monkeypatch, tmp_path):
    refresh_flags = []
    requests = []

    class FakeResponse:
        reason = "OK"

        def __init__(self, status, chunks):
            self.status = status
            self.chunks = list(chunks)

        def getheaders(self):
            return [("Content-Type", "application/json")]

        def read(self, size=None):
            return self.chunks.pop(0) if self.chunks else b""

    responses = [
        FakeResponse(401, [b'{"error":"expired"}']),
        FakeResponse(200, [b'{"ok":true}', b""]),
    ]

    class FakeConnection:
        def __init__(self, host, port, timeout):
            pass

        def request(self, method, path, body=None, headers=None):
            requests.append((method, path, body, headers))

        def getresponse(self):
            return responses.pop(0)

        def close(self):
            pass

    def fake_headers(config, incoming, *, force_oauth_refresh=False):
        refresh_flags.append(force_oauth_refresh)
        token = "refreshed" if force_oauth_refresh else "initial"
        return {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(provider_relay.http.client, "HTTPSConnection", FakeConnection)
    monkeypatch.setattr(provider_relay, "upstream_headers", fake_headers)

    handler = object.__new__(ProviderRelayHandler)
    handler.relay_config = RelayConfig(
        provider="openai",
        upstream_host="chatgpt.com",
        credential=None,
        credential_kind="codex-oauth",
        blocked_tool_types=CODEX_SUBSCRIPTION_RELAY_SPEC.blocked_tool_types,
        blocked_tool_prefixes=CODEX_SUBSCRIPTION_RELAY_SPEC.blocked_tool_prefixes,
        allowed_client_tool_types=CODEX_SUBSCRIPTION_RELAY_SPEC.allowed_client_tool_types,
        allow_external_tools=False,
        log_dir=tmp_path,
        credential_file=tmp_path / "auth.json",
        allowed_path_prefixes=CODEX_SUBSCRIPTION_RELAY_SPEC.allowed_path_prefixes,
    )
    handler.command = "POST"
    handler.path = "/backend-api/codex/responses"
    handler.headers = headers(Content_Type="application/json", Content_Length="2")
    handler.rfile = io.BytesIO(b"{}")
    handler.wfile = io.BytesIO()
    handler.timeout = 7
    sent_status = []
    handler.send_response = lambda status, reason=None: sent_status.append((status, reason))
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler.send_error = lambda status: sent_status.append((status, None))

    handler._relay()

    assert refresh_flags == [False, True]
    assert [request[3]["Authorization"] for request in requests] == [
        "Bearer initial",
        "Bearer refreshed",
    ]
    assert sent_status == [(200, "OK")]
    assert handler.wfile.getvalue() == b'{"ok":true}'
