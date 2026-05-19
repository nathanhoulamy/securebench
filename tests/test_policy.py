import pytest

from securebench.sandboxes.policy import CommandPolicy, PolicySandbox, PolicyViolation, normalize_command
from securebench.sandboxes import CommandResult, Sandbox


class FakeSandbox(Sandbox):
    def __init__(self):
        self.commands = []

    def run(self, command, *, workdir=None, timeout=None):
        self.commands.append((command, workdir, timeout))
        normalized = tuple(command) if not isinstance(command, str) else ("sh", "-lc", command)
        return CommandResult(normalized, 0, "ok", "")

    def write_file(self, path, content):
        pass

    def read_file(self, path):
        return ""

    def extract_file(self, path):
        return b""


def test_normalize_command_splits_shell_strings_for_policy_checks():
    assert normalize_command("pytest tests/test_file.py") == ("pytest", "tests/test_file.py")
    assert normalize_command(["python", "file.py"]) == ("python", "file.py")


def test_command_policy_allows_when_allow_list_matches():
    policy = CommandPolicy(allow={"pytest"})
    attempt = policy.check("pytest tests")

    assert attempt.allowed is True
    assert attempt.command_name == "pytest"
    assert policy.attempts == [attempt]


def test_command_policy_denies_disallowed_command_and_logs_attempt():
    policy = CommandPolicy(allow={"pytest"})

    with pytest.raises(PolicyViolation, match="not in allow list"):
        policy.enforce("curl https://example.com")

    assert policy.attempts[0].command_name == "curl"
    assert policy.attempts[0].allowed is False


def test_command_policy_deny_takes_precedence():
    policy = CommandPolicy(allow={"pytest"}, deny={"pytest"})

    with pytest.raises(PolicyViolation, match="is denied"):
        policy.enforce("pytest")


def test_policy_sandbox_enforces_before_delegating():
    sandbox = FakeSandbox()
    policy_sandbox = PolicySandbox(sandbox, CommandPolicy(allow={"pytest"}))

    result = policy_sandbox.run("pytest tests", workdir="repo", timeout=1)

    assert result.stdout == "ok"
    assert sandbox.commands == [("pytest tests", "repo", 1)]


def test_policy_sandbox_does_not_delegate_denied_command():
    sandbox = FakeSandbox()
    policy_sandbox = PolicySandbox(sandbox, CommandPolicy(deny={"*"}))

    with pytest.raises(PolicyViolation):
        policy_sandbox.run("pytest tests")

    assert sandbox.commands == []
