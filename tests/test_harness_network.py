from types import SimpleNamespace

import pytest

from securebench.errors import ConfigError
from securebench.harnesses.claude_code import CLAUDE_CODE_PROVIDER_RELAY_SPEC
from securebench.harnesses.codex import CODEX_PROVIDER_RELAY_SPEC
from securebench.harnesses.egress_proxy import is_allowed_destination, split_host_port
from securebench.harnesses.network import (
    DockerEgressPolicy,
    DockerProviderRelayPolicy,
    allowed_domains_config,
    domain_allowed,
    effective_allowed_domains,
    relay_decision_summary,
)


def test_allowed_domains_config_normalizes_and_deduplicates():
    assert allowed_domains_config(["Example.COM", "api.example.com.", "example.com"]) == (
        "example.com",
        "api.example.com",
    )


@pytest.mark.parametrize(
    "value",
    [
        "example.com",
        ["https://example.com"],
        ["example.com:443"],
        ["example.com/path"],
        ["*.example.com"],
        ["127.0.0.1"],
        ["::1"],
        ["localhost"],
        ["internal"],
        [""],
    ],
)
def test_allowed_domains_config_rejects_invalid_entries(value):
    with pytest.raises(ConfigError, match="allowed_domains"):
        allowed_domains_config(value)


def test_effective_allowed_domains_keeps_provider_domains_out_of_generic_egress():
    assert effective_allowed_domains("codex", ("pypi.org",)) == ("pypi.org",)
    assert effective_allowed_domains("claude_code", ("docs.python.org",)) == ("docs.python.org",)
    assert effective_allowed_domains("command", ("docs.python.org",)) == ("docs.python.org",)
    assert effective_allowed_domains("command", ()) == ()


def test_domain_allowed_matches_exact_domain_and_subdomains_only():
    allowed = ("example.com",)

    assert domain_allowed("example.com", allowed) is True
    assert domain_allowed("api.example.com", allowed) is True
    assert domain_allowed("badexample.com", allowed) is False


def test_proxy_destination_policy_matches_domains_and_standard_ports():
    allowed = ("example.com",)

    assert is_allowed_destination("example.com", 443, allowed) is True
    assert is_allowed_destination("api.example.com", 443, allowed) is True
    assert is_allowed_destination("example.com", 80, allowed) is True
    assert is_allowed_destination("badexample.com", 443, allowed) is False
    assert is_allowed_destination("example.com", 22, allowed) is False


def test_proxy_connect_authority_parsing_rejects_malformed_ports():
    assert split_host_port("example.com:443", 443) == ("example.com", 443)
    assert split_host_port("[::1]:443", 443) == ("::1", 443)
    assert split_host_port("example.com:not-a-port", 443) is None
    assert split_host_port("example.com:70000", 443) is None
    assert split_host_port("[::1", 443) is None
    assert split_host_port("[::1]suffix", 443) is None


def test_docker_egress_policy_empty_allowlist_disables_network(monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    with DockerEgressPolicy(()) as egress:
        assert egress.network == "none"
        assert egress.env == {}
        assert egress.allowed_domains == ()

    assert commands == []


def test_docker_egress_policy_creates_proxy_network_and_cleans_up(monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    with DockerEgressPolicy(("api.openai.com",)) as egress:
        assert egress.network.startswith("securebench-egress-")
        assert egress.env["HTTPS_PROXY"] == "http://securebench-egress-proxy:8080"
        assert egress.allowed_domains == ("api.openai.com",)

    assert commands[0][:4] == ["docker", "network", "create", "--internal"]
    assert commands[1][:5] == ["docker", "run", "-d", "--rm", "--name"]
    assert "--network" in commands[1]
    assert "bridge" in commands[1]
    assert "SECUREBENCH_ALLOWED_DOMAINS=api.openai.com" in commands[1]
    assert commands[2][:4] == ["docker", "network", "connect", "--alias"]
    assert commands[3][:3] == ["docker", "rm", "-f"]
    assert commands[4][:3] == ["docker", "network", "rm"]


def test_docker_egress_policy_cleans_up_after_start_failure(monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:3] == ["docker", "network", "connect"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="connect failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(ConfigError, match="connect egress proxy"):
        with DockerEgressPolicy(("api.openai.com",)):
            pass

    assert commands[-2][:3] == ["docker", "rm", "-f"]
    assert commands[-1][:3] == ["docker", "network", "rm"]


def test_harness_provider_relay_specs_own_base_urls():
    assert CODEX_PROVIDER_RELAY_SPEC.base_url == "http://securebench-provider-relay:8090/v1"
    assert CLAUDE_CODE_PROVIDER_RELAY_SPEC.base_url == "http://securebench-provider-relay:8090"


def test_docker_provider_relay_policy_starts_relay_without_generic_proxy(monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr("subprocess.run", fake_run)

    with DockerProviderRelayPolicy(CODEX_PROVIDER_RELAY_SPEC, (), allow_external_tools=False) as egress:
        assert egress.network.startswith("securebench-egress-")
        assert egress.env == {}
        assert egress.provider == "openai"
        assert egress.provider_base_url == "http://securebench-provider-relay:8090/v1"
        assert egress.provider_relay_enabled is True
        assert egress.allow_external_tools is False

    assert commands[0][:4] == ["docker", "network", "create", "--internal"]
    relay_run = commands[1]
    assert relay_run[:5] == ["docker", "run", "-d", "--rm", "--name"]
    assert ["-e", "OPENAI_API_KEY"] == relay_run[relay_run.index("-e") : relay_run.index("-e") + 2]
    assert "secret" not in relay_run
    assert "SECUREBENCH_PROVIDER=openai" in relay_run
    assert "SECUREBENCH_UPSTREAM_HOST=api.openai.com" in relay_run
    assert "SECUREBENCH_API_KEY_ENV=OPENAI_API_KEY" in relay_run
    assert 'SECUREBENCH_BLOCKED_TOOL_TYPES=["code_interpreter", "computer_use", "file_search", "image_generation", "mcp", "web_search"]' in relay_run
    assert 'SECUREBENCH_BLOCKED_TOOL_PREFIXES=["computer_use_", "web_search_"]' in relay_run
    assert 'SECUREBENCH_ALLOWED_CLIENT_TOOL_TYPES=["apply_patch", "custom", "function", "shell"]' in relay_run
    assert "SECUREBENCH_ALLOW_EXTERNAL_TOOLS=false" in relay_run
    assert commands[2][:4] == ["docker", "network", "connect", "--alias"]
    assert "securebench-provider-relay" in commands[2]
    assert commands[3][:3] == ["docker", "rm", "-f"]
    assert commands[4][:3] == ["docker", "network", "rm"]


def test_docker_provider_relay_policy_starts_generic_proxy_when_domains_allowed(monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setattr("subprocess.run", fake_run)

    with DockerProviderRelayPolicy(
        CLAUDE_CODE_PROVIDER_RELAY_SPEC,
        ("docs.python.org",),
        allow_external_tools=True,
    ) as egress:
        assert egress.env["HTTPS_PROXY"] == "http://securebench-egress-proxy:8080"
        assert "securebench-provider-relay" in egress.env["NO_PROXY"]
        assert egress.provider_base_url == "http://securebench-provider-relay:8090"
        assert egress.allow_external_tools is True

    assert "SECUREBENCH_ALLOWED_DOMAINS=docs.python.org" in commands[1]
    assert "securebench-egress-proxy" in commands[2]
    relay_run = commands[3]
    assert ["-e", "ANTHROPIC_API_KEY"] == relay_run[relay_run.index("-e") : relay_run.index("-e") + 2]
    assert "SECUREBENCH_PROVIDER=anthropic" in relay_run
    assert "SECUREBENCH_UPSTREAM_HOST=api.anthropic.com" in relay_run
    assert "SECUREBENCH_API_KEY_ENV=ANTHROPIC_API_KEY" in relay_run
    assert "SECUREBENCH_ALLOW_EXTERNAL_TOOLS=true" in relay_run


def test_relay_decision_summary_counts_forwarded_and_blocked(tmp_path):
    log = tmp_path / "decisions.jsonl"
    log.write_text(
        '{"status": "forwarded"}\n'
        '{"status": "blocked"}\n'
        'not-json\n'
    )

    assert relay_decision_summary(tmp_path) == {
        "provider_relay_requests": 2,
        "provider_relay_blocked": 1,
    }
