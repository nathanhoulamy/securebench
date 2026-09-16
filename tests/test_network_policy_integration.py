import pytest

from securebench.errors import ConfigError
from securebench.harnesses.claude_code import ClaudeCodeHarnessProducer
from securebench.harnesses.command import CommandHarnessProducer
from securebench.harnesses.codex import CodexHarnessProducer
from securebench.harnesses.opencode import OpenCodeHarnessProducer
from securebench.network_policy import NetworkPolicy


@pytest.mark.parametrize(
    "producer",
    [
        lambda policy: CommandHarnessProducer(command="true", network_policy=policy),
        lambda policy: CodexHarnessProducer(model="test", network_policy=policy),
        lambda policy: ClaudeCodeHarnessProducer(network_policy=policy),
        lambda policy: OpenCodeHarnessProducer(network_policy=policy),
    ],
)
def test_each_harness_constructor_keeps_network_policy(producer):
    policy = NetworkPolicy(mode="extend", allowed_domains=("global.example.com",))

    assert producer(policy).network_policy == policy


@pytest.mark.parametrize(
    "producer",
    [
        lambda: CommandHarnessProducer(command="true", allowed_domains=("example.com",)),
        lambda: CodexHarnessProducer(model="test", allowed_domains=("example.com",)),
        lambda: ClaudeCodeHarnessProducer(allowed_domains=("example.com",)),
        lambda: OpenCodeHarnessProducer(allowed_domains=("example.com",)),
    ],
)
def test_each_harness_constructor_rejects_legacy_allowed_domains(producer):
    with pytest.raises(ConfigError, match="move it to top-level network_policy"):
        producer()
