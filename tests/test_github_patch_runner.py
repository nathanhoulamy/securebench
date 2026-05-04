import pytest

from securebench.runners import GitHubPatchRunner
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import GitHubPatchTask, MultipleChoiceTask


class FakeSandbox(Sandbox):
    def __init__(self, exit_codes=None):
        self.files = {}
        self.calls = []
        self.exit_codes = list(exit_codes or [])

    def run(self, command, *, workdir=None, timeout=None):
        self.calls.append((command, workdir, timeout))
        exit_code = self.exit_codes.pop(0) if self.exit_codes else 0
        stdout = "diff --git a/file.py b/file.py\n" if command == ["git", "diff", "--binary"] else ""
        return CommandResult(tuple(command) if not isinstance(command, str) else ("sh", "-lc", command), exit_code, stdout, "")

    def write_file(self, path, content):
        self.files[str(path)] = content

    def read_file(self, path):
        return self.files[str(path)]

    def extract_file(self, path):
        return self.files[str(path)].encode()


def make_task():
    return GitHubPatchTask(
        id="example__repo-1",
        benchmark_id="example",
        task_type="github_patch",
        repo="example/repo",
        base_commit="abc123",
        instructions="Fix the issue.",
    )


def test_github_patch_runner_clones_applies_patch_runs_tests_and_collects_diff():
    sandbox = FakeSandbox()
    result = GitHubPatchRunner(sandbox=sandbox, timeout=5).run(
        make_task(),
        "diff --git ...",
        test_commands=("pytest tests/test_bug.py",),
    )

    assert sandbox.calls == [
        (["git", "clone", "https://github.com/example/repo.git", "repo"], None, 5),
        (["git", "checkout", "abc123"], "repo", 5),
        (["git", "apply", "/workspace/candidate.patch"], "repo", 5),
        ("pytest tests/test_bug.py", "repo", 5),
        (["git", "diff", "--binary"], "repo", 5),
    ]
    assert sandbox.files["repo/SECUREBENCH_TASK.md"] == "Fix the issue."
    assert sandbox.files["candidate.patch"] == "diff --git ..."
    assert result.passed is True
    assert result.metadata["model_patch"] == "diff --git a/file.py b/file.py\n"


def test_github_patch_runner_reports_failure_from_command_exit_code():
    sandbox = FakeSandbox(exit_codes=[0, 0, 1, 0])
    result = GitHubPatchRunner(sandbox=sandbox).run(make_task(), "bad patch")

    assert result.passed is False
    assert result.score == 0.0
    assert result.metadata["exit_codes"] == [0, 0, 1, 0]


def test_github_patch_runner_requires_patch_task():
    task = MultipleChoiceTask(
        id="mmlu/math/test/7",
        benchmark_id="mmlu",
        task_type="multiple_choice",
    )

    with pytest.raises(TypeError, match="GitHubPatchRunner requires GitHubPatchTask"):
        GitHubPatchRunner(sandbox=FakeSandbox()).run(task, "")
