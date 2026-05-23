from pathlib import Path

import pytest

from securebench.benchmark_compiler import compile_benchmark_row
from securebench.benchmark_pack import BenchmarkPackManifest, BenchmarkRow
from securebench.candidates.extraction import (
    default_extraction_spec,
    extract_candidate,
    extraction_instructions,
    file_extraction_spec,
    stdout_extraction_spec,
)
from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult


class FakeSandbox:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.commands = []

    def run(self, command, *, workdir=None, timeout=None):
        self.commands.append((command, workdir, timeout))
        if tuple(command) == ("git", "diff", "--binary"):
            return CommandResult(tuple(command), 0, "diff --git a/app.py b/app.py\n", "")
        return CommandResult(tuple(command), 0, "", "")

    def read_file(self, path):
        return (self.root / path).read_text()


def code_task(*, environment=None):
    return compile_benchmark_row(
        BenchmarkRow(
            id="code-1",
            family="code_completion",
            input={"prompt": "Write add."},
            eval={"tests": {"source": "inline", "code": "assert candidate(1, 2) == 3"}},
            environment={} if environment is None else environment,
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def mc_task():
    return compile_benchmark_row(
        BenchmarkRow(
            id="mc-1",
            family="multiple_choice",
            input={"question": "2 + 2?", "choices": ["1", "2", "4"]},
            eval={"answer": "4"},
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def repo_patch_task(*, environment=None):
    return compile_benchmark_row(
        BenchmarkRow(
            id="repo-1",
            family="repo_patch",
            input={"repo": "repo/", "base_commit": "abc123", "instructions": "Fix it."},
            eval={"tests": {"source": "command", "command": "pytest -q"}},
            environment={} if environment is None else environment,
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def terminal_task(*, environment=None):
    return compile_benchmark_row(
        BenchmarkRow(
            id="term-1",
            family="terminal_task",
            input={"instructions": "Create output.txt."},
            eval={"checker": {"command": "test -f output.txt"}},
            environment={} if environment is None else environment,
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def test_default_extraction_spec_uses_candidate_file_for_code_completion():
    spec = default_extraction_spec(code_task(), allow_stdout=False)

    assert spec.mode == "file"
    assert spec.candidate_kind == "code"
    assert spec.path == "candidate.py"
    assert "candidate.py" in extraction_instructions(spec)


def test_default_extraction_spec_uses_git_diff_for_repo_patch_workdir():
    spec = default_extraction_spec(
        repo_patch_task(environment={"workdir": "/workspace/repo"}),
        allow_stdout=False,
    )

    assert spec.mode == "git_diff"
    assert spec.candidate_kind == "patch"
    assert spec.workdir == "/workspace/repo"


def test_default_extraction_spec_uses_workspace_for_terminal_task():
    spec = default_extraction_spec(terminal_task(), allow_stdout=False)

    assert spec.mode == "workspace"
    assert spec.candidate_kind == "workspace"
    assert "final workspace state" in extraction_instructions(spec)


def test_default_extraction_spec_uses_candidate_file_for_text_when_stdout_disabled():
    spec = default_extraction_spec(mc_task(), allow_stdout=False)

    assert spec.mode == "file"
    assert spec.candidate_kind == "text"
    assert spec.path == "candidate.txt"
    assert "candidate.txt" in extraction_instructions(spec)


def test_extract_candidate_from_stdout_shapes_text_artifact(tmp_path):
    artifact = extract_candidate(
        mc_task(),
        FakeSandbox(tmp_path),
        CommandResult(("produce",), 0, "4\n", "warn"),
        stdout_extraction_spec(mc_task()),
    )

    assert artifact.text == "4\n"
    assert artifact.patch is None
    assert artifact.stdout == "4\n"
    assert artifact.stderr == "warn"
    assert artifact.metadata["candidate_extraction"] == "stdout"


def test_extract_candidate_from_file_shapes_code_artifact(tmp_path):
    (tmp_path / "candidate.py").write_text("def add(a, b):\n    return a + b\n")

    artifact = extract_candidate(
        code_task(),
        FakeSandbox(tmp_path),
        CommandResult(("codex",), 0, "events", ""),
        file_extraction_spec(code_task(), "candidate.py"),
    )

    assert artifact.text == "def add(a, b):\n    return a + b\n"
    assert artifact.patch is None
    assert artifact.metadata["candidate_path"] == "candidate.py"


def test_extract_candidate_file_mode_reports_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="candidate.py"):
        extract_candidate(
            code_task(),
            FakeSandbox(tmp_path),
            CommandResult(("codex",), 0, "", ""),
            file_extraction_spec(code_task(), "candidate.py"),
        )


def test_extract_candidate_from_git_diff_shapes_patch_artifact(tmp_path):
    task = repo_patch_task(environment={"workdir": "/workspace/repo"})
    sandbox = FakeSandbox(tmp_path)
    artifact = extract_candidate(
        task,
        sandbox,
        CommandResult(("codex",), 0, "events", ""),
        default_extraction_spec(task, allow_stdout=False),
        timeout=30,
    )

    assert artifact.text is None
    assert artifact.patch == "diff --git a/app.py b/app.py\n"
    assert artifact.metadata["candidate_extraction"] == "git_diff"
    assert artifact.metadata["candidate_workdir"] == "/workspace/repo"
    assert sandbox.commands == [(["git", "diff", "--binary"], "/workspace/repo", 30)]


def test_extract_candidate_from_workspace_shapes_workspace_artifact(tmp_path):
    task = terminal_task()
    artifact = extract_candidate(
        task,
        FakeSandbox(tmp_path),
        CommandResult(("codex",), 0, "events", ""),
        default_extraction_spec(task, allow_stdout=False),
    )

    assert artifact.text is None
    assert artifact.patch is None
    assert artifact.workspace == str(tmp_path)
    assert artifact.metadata["candidate_kind"] == "workspace"
    assert artifact.metadata["candidate_extraction"] == "workspace"
