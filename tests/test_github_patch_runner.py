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
        test_groups={
            "regression": ("tests/test_bug.py::test_fixed",),
            "smoke": ("tests/test_existing.py::test_still_passes",),
        },
        hidden_patches={
            "tests": "diff --git a/tests/test_hidden.py b/tests/test_hidden.py\n",
        },
    )


def test_github_patch_runner_clones_applies_patch_runs_tests_and_records_candidate_patch():
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
    ]
    assert sandbox.files["repo/SECUREBENCH_TASK.md"] == "Fix the issue."
    assert sandbox.files["candidate.patch"] == "diff --git ..."
    assert result.passed is True
    assert result.metadata["model_patch"] == "diff --git ..."


def test_github_patch_runner_uses_configured_setup_and_test_commands():
    sandbox = FakeSandbox()
    result = GitHubPatchRunner(
        sandbox=sandbox,
        repo_dir="worktree",
        setup_commands=("python -m pip install -e .",),
        test_commands=("pytest tests",),
        timeout=9,
    ).run(make_task(), "diff --git ...")

    assert sandbox.calls == [
        (["git", "clone", "https://github.com/example/repo.git", "worktree"], None, 9),
        (["git", "checkout", "abc123"], "worktree", 9),
        (["git", "apply", "/workspace/candidate.patch"], "worktree", 9),
        ("python -m pip install -e .", "worktree", 9),
        ("pytest tests", "worktree", 9),
    ]
    assert result.metadata["repo_dir"] == "worktree"
    assert result.metadata["setup_command_count"] == 1
    assert result.metadata["test_command_count"] == 1


def test_github_patch_runner_applies_hidden_patches_and_generates_test_command_from_groups():
    sandbox = FakeSandbox()
    result = GitHubPatchRunner(
        sandbox=sandbox,
        apply_hidden_patches=("tests",),
        test_group_names=("regression", "smoke"),
        test_command_template="pytest {tests}",
        timeout=6,
    ).run(make_task(), "candidate patch")

    assert sandbox.calls == [
        (["git", "clone", "https://github.com/example/repo.git", "repo"], None, 6),
        (["git", "checkout", "abc123"], "repo", 6),
        (["git", "apply", "/workspace/candidate.patch"], "repo", 6),
        (["git", "apply", "/workspace/hidden-tests.patch"], "repo", 6),
        ("pytest tests/test_bug.py::test_fixed tests/test_existing.py::test_still_passes", "repo", 6),
    ]
    assert sandbox.files["candidate.patch"] == "candidate patch"
    assert sandbox.files["hidden-tests.patch"] == "diff --git a/tests/test_hidden.py b/tests/test_hidden.py\n"
    assert result.metadata["selected_test_count"] == 2
    assert result.metadata["test_group_names"] == ["regression", "smoke"]
    assert result.metadata["applied_hidden_patch_names"] == ["tests"]
    assert "test_hidden.py" not in str(result.metadata)
    assert "test_hidden.py" not in result.stdout


def test_github_patch_runner_fails_when_configured_hidden_patch_is_missing():
    sandbox = FakeSandbox()
    task = GitHubPatchTask(
        id="example__repo-1",
        benchmark_id="example",
        task_type="github_patch",
        repo="example/repo",
        base_commit="abc123",
        instructions="Fix the issue.",
    )

    result = GitHubPatchRunner(sandbox=sandbox, apply_hidden_patches=("tests",)).run(task, "")

    assert result.passed is False
    assert result.metadata["exit_codes"] == [0, 0, 1]
    assert "Hidden patch 'tests' is not available" in result.stderr


def test_github_patch_runner_uses_fresh_sandbox_from_factory_per_run():
    sandboxes = []

    def make_sandbox():
        sandbox = FakeSandbox()
        sandboxes.append(sandbox)
        return sandbox

    runner = GitHubPatchRunner(sandbox_factory=make_sandbox)

    runner.run(make_task(), "")
    runner.run(make_task(), "")

    assert len(sandboxes) == 2
    assert sandboxes[0] is not sandboxes[1]
    assert sandboxes[0].calls == [
        (["git", "clone", "https://github.com/example/repo.git", "repo"], None, 120.0),
        (["git", "checkout", "abc123"], "repo", 120.0),
    ]
    assert sandboxes[1].calls == [
        (["git", "clone", "https://github.com/example/repo.git", "repo"], None, 120.0),
        (["git", "checkout", "abc123"], "repo", 120.0),
    ]


def test_github_patch_runner_rejects_both_sandbox_and_factory():
    with pytest.raises(ValueError, match="either sandbox or sandbox_factory"):
        GitHubPatchRunner(sandbox=FakeSandbox(), sandbox_factory=FakeSandbox)


def test_github_patch_runner_reports_failure_from_command_exit_code():
    sandbox = FakeSandbox(exit_codes=[0, 0, 1, 0])
    result = GitHubPatchRunner(sandbox=sandbox).run(make_task(), "bad patch")

    assert result.passed is False
    assert result.score == 0.0
    assert result.metadata["exit_codes"] == [0, 0, 1]


def test_github_patch_runner_requires_patch_task():
    task = MultipleChoiceTask(
        id="mmlu/math/test/7",
        benchmark_id="mmlu",
        task_type="multiple_choice",
    )

    with pytest.raises(TypeError, match="GitHubPatchRunner requires GitHubPatchTask"):
        GitHubPatchRunner(sandbox=FakeSandbox()).run(task, "")
