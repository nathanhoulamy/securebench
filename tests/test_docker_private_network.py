"""Configuration failures must precede any guest launch, on all three paths."""
import copy
import json
import subprocess
from types import SimpleNamespace

import pytest

from securebench.docker_network import ISOLATED_BRIDGE_ARGUMENTS, validate_private_network
from securebench.errors import ConfigError
from securebench.harnesses.network import DockerEgressPolicy, DockerProviderRelayPolicy, ProviderRelaySpec
from securebench.verification.models import VerificationInfrastructureError
from securebench.verification.trusted_helpers import TrustedHelperEvaluation


VALID = ["bridge", True, "isolated", "isolated", False,
         {"Driver": "default", "Config": [{"Subnet": "172.18.0.0/16"}]}]


def test_valid_isolated_configuration_and_ipv6():
    validate_private_network("test", lambda _: json.dumps(VALID))
    dual = copy.deepcopy(VALID)
    dual[4] = True
    dual[5]["Config"].append({"Subnet": "fd00::/64"})
    validate_private_network("test", lambda _: json.dumps(dual))
    assert "--ipv6" not in ISOLATED_BRIDGE_ARGUMENTS


@pytest.mark.parametrize("field,value", [(0, "overlay"), (1, False), (1, 1),
    (2, "nat"), (3, "nat"), (4, None), (5, {}),
    (5, {"Driver": "default", "Config": [{"Subnet": "172.18.0.0/16", "Gateway": "172.18.0.1"}]}),
    (5, {"Driver": "default", "Config": [{"Subnet": "broken"}]})])
def test_rejects_misconfigured_network(field, value):
    config = copy.deepcopy(VALID)
    config[field] = value
    with pytest.raises(ConfigError, match="not isolated"):
        validate_private_network("test", lambda _: json.dumps(config))


@pytest.mark.parametrize("raw", ["", "{}", "null", "[]", "x" * 16385])
def test_rejects_malformed_inspection(raw):
    with pytest.raises(ConfigError):
        validate_private_network("test", lambda _: raw)


@pytest.mark.parametrize("path", ["egress", "relay", "helper"])
@pytest.mark.parametrize("failure", ["create", "inspect", "timeout", "gateway", "interrupt"])
def test_failure_cleans_up_before_containers_attach(monkeypatch, path, failure):
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["timeout"] == 30
        operation = command[2] if command[1] == "network" else command[1]
        if operation == failure:
            return SimpleNamespace(returncode=1, stdout="", stderr="unsupported isolated mode")
        if operation == "inspect" and failure == "interrupt":
            raise KeyboardInterrupt
        if operation == "inspect" and failure == "timeout":
            raise subprocess.TimeoutExpired(command, 30)
        config = copy.deepcopy(VALID)
        if failure == "gateway":
            config[5]["Config"][0]["Gateway"] = "172.18.0.1"
        return SimpleNamespace(returncode=0, stdout=json.dumps(config), stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    if path == "egress":
        start = DockerEgressPolicy(("allowed.test",)).__enter__
    elif path == "relay":
        monkeypatch.setenv("SECUREBENCH_TEST_KEY", "test-only")
        spec = ProviderRelaySpec("openai", "allowed.test", "SECUREBENCH_TEST_KEY", "bearer", "http://relay")
        start = DockerProviderRelayPolicy(spec, ()).__enter__
    else:
        catalog = SimpleNamespace(validate_declaration=lambda _: SimpleNamespace(helper_access="http"))
        evaluation = TrustedHelperEvaluation(task=None, check=SimpleNamespace(trusted_helpers=[None]),
            catalog=catalog, challenge_id="test", evaluation_id="test")
        start = evaluation.start
    with pytest.raises((ConfigError, VerificationInfrastructureError, KeyboardInterrupt)):
        start()
    assert commands[0][3:3 + len(ISOLATED_BRIDGE_ARGUMENTS)] == ISOLATED_BRIDGE_ARGUMENTS
    assert any(c[:3] == ["docker", "network", "rm"] and c[-1] == commands[0][-1] for c in commands)
    assert not any(c[1] == "run" or c[:3] == ["docker", "network", "connect"] for c in commands)
    if failure != "create":
        assert commands[1][:3] == ["docker", "network", "inspect"]


def test_helper_keeps_network_ownership_when_removal_fails(monkeypatch):
    evaluation = TrustedHelperEvaluation(task=None, check=None, catalog=None,
        challenge_id="test", evaluation_id="test")
    evaluation._network_name = "owned-network"
    evaluation.network = "owned-network"
    calls = []
    def remove(name):
        calls.append(name)
        if len(calls) == 1:
            raise VerificationInfrastructureError("trusted_helper_cleanup_failed", "retry removal", source="trusted_helper")
    monkeypatch.setattr("securebench.verification.trusted_helpers._remove_network", remove)
    with pytest.raises(VerificationInfrastructureError):
        evaluation.close()
    assert evaluation._network_name == "owned-network"
    evaluation.close()
    assert calls == ["owned-network", "owned-network"]
    assert evaluation.network == "none"
