import pytest

from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import task_from_spec
from securebench.verifiers.repo_patch import (
    RepoPatchVerifier,
    command_tests,
    environment_workdir_for_task,
)


class FakeSandbox(Sandbox):
    def __init__(self, *, image=None, results=None):
        self.image = image
        self.results = list(results or [])
        self.commands = []
        self.files = {}

    def run(self, command, *, workdir=None, timeout=None):
        normalized = tuple(command) if not isinstance(command, str) else ("sh", "-lc", command)
        self.commands.append((command, workdir, timeout))
        if self.results:
            result = self.results.pop(0)
            return CommandResult(normalized, result[0], result[1], result[2])
        return CommandResult(normalized, 0, "", "")

    def write_file(self, path, content):
        self.files[str(path)] = content

    def read_file(self, path):
        return self.files[str(path)]

    def extract_file(self, path):
        return self.files[str(path)].encode()


def make_task(*, image="repo-image:latest", workdir="/testbed", tests=None):
    return task_from_spec(
        {
            "id": "repo-pack/fix-bug",
            "benchmark_id": "repo-pack",
            "task_type": "repo_patch",
            "metadata": {
                "environment": {"image": image, "workdir": workdir},
            },
            "resources": {
                "repo": {"value": "example/project", "visibility": "public"},
                "base_commit": {"value": "abc123", "visibility": "public"},
                "instructions": {"value": "Fix the bug.", "visibility": "public"},
                "tests": {
                    "value": tests
                    if tests is not None
                    else {
                        "source": "command",
                        "command": ["python", "-m", "pytest", "tests/test_bug.py"],
                        "test_patch": {
                            "source": "inline",
                        "patch": "diff --git a/tests/test_bug.py b/tests/test_bug.py\n",
                        },
                        "setup_patch": {
                            "source": "inline",
                            "patch": "diff --git a/bug.py b/bug.py\n",
                        },
                    },
                    "visibility": "evaluation_inputs",
                },
            },
        }
    )


def test_command_tests_parse_command_test_shape():
    tests = command_tests(make_task(tests={"source": "command", "command": "pytest -q", "timeout_seconds": 12}))

    assert tests.command == "pytest -q"
    assert tests.timeout_seconds == 12.0
    assert tests.test_patch is None


def test_environment_workdir_for_task_requires_workdir():
    assert environment_workdir_for_task(make_task(workdir="/repo")) == "/repo"

    with pytest.raises(ConfigError, match="environment.workdir"):
        environment_workdir_for_task(make_task(workdir=""))


def test_repo_patch_verifier_applies_candidate_and_test_patch_then_runs_checks():
    sandbox = FakeSandbox(results=[(0, "abc123\n", ""), (0, "", ""), (0, "", ""), (0, "", ""), (0, "passed", "")])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox, timeout_seconds=99)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert sandbox.image is None
    assert sandbox.files["securebench/candidate.patch"] == "diff --git a/app.py b/app.py\n"
    assert sandbox.files["securebench/evaluation_inputs/setup.patch"].startswith("diff --git")
    assert sandbox.files["securebench/evaluation_inputs/test.patch"].startswith("diff --git")
    assert sandbox.commands == [
        (["git", "rev-parse", "HEAD"], "/testbed", 99.0),
        (["git", "apply", "--binary", "/securebench-workspace/securebench/evaluation_inputs/setup.patch"], "/testbed", 99.0),
        (["git", "apply", "--binary", "/securebench-workspace/securebench/candidate.patch"], "/testbed", 99.0),
        (["git", "apply", "--binary", "/securebench-workspace/securebench/evaluation_inputs/test.patch"], "/testbed", 99.0),
        (("python", "-m", "pytest", "tests/test_bug.py"), "/testbed", 99.0),
    ]
    assert result.status == "passed"
    assert result.passed is True
    assert result.metadata["verifier"] == "repo_patch"
    assert result.metadata["image"] == "repo-image:latest"
    assert result.metadata["phase"] == "checks"


def test_repo_patch_verifier_reports_candidate_patch_failure():
    sandbox = FakeSandbox(results=[(0, "abc123\n", ""), (0, "", ""), (1, "", "bad patch")])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "not a patch")

    assert result.status == "failed"
    assert result.passed is False
    assert result.stderr == "bad patch"
    assert result.metadata["phase"] == "candidate_patch"


def test_repo_patch_verifier_reports_empty_candidate_patch_as_failed_result():
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: FakeSandbox())

    result = verifier.verify(make_task(), "")

    assert result.status == "failed"
    assert result.passed is False
    assert result.stderr == "empty candidate patch"
    assert result.metadata["phase"] == "candidate_patch"
    assert result.metadata["failure_reason"] == "empty_candidate_patch"


def test_repo_patch_verifier_reports_failed_checks():
    sandbox = FakeSandbox(results=[(0, "abc123\n", ""), (0, "", ""), (0, "", ""), (0, "", ""), (1, "", "failed")])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "failed"
    assert result.passed is False
    assert result.score == 0.0
    assert result.stderr == "failed"
    assert result.metadata["exit_code"] == 1
