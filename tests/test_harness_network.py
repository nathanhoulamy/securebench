from types import SimpleNamespace

import pytest

from securebench.errors import ConfigError
from securebench.harnesses.egress_proxy import is_allowed_destination, split_host_port
from securebench.harnesses.network import (
    DockerEgressPolicy,
    allowed_domains_config,
    domain_allowed,
    effective_allowed_domains,
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


def test_effective_allowed_domains_adds_provider_defaults():
    assert effective_allowed_domains("codex", ("pypi.org",)) == ("api.openai.com", "pypi.org")
    assert effective_allowed_domains("claude_code", ("docs.python.org",)) == (
        "api.anthropic.com",
        "docs.python.org",
    )
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
