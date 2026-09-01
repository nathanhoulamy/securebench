from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck, DirectoryTreeEntry
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_module,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/git-leak-recovery"
IMAGE = (
    "alexgshaw/git-leak-recovery@"
    "sha256:62160e522a4238b8bcd522411ea97b5b200f811e5899d34947e66809bef7e586"
)
ORACLE_ROOT = PACK / "v2" / "hidden" / "git-leak-recovery" / "oracle"
ORACLE = ORACLE_ROOT / "oracle.py"
SOURCE_VERIFIER = PACK / "hidden" / "git-leak-recovery" / "tests" / "test_outputs.py"
EXPECTED = "secret[lost_and_found_in_git]"
REQUIRED_COMMIT = "chore: init e665d1a2-04a7-4e61-b523-e897e231d9cc"


def compiled_task():
    return load_terminal_task(TASK_ID)


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *arguments),
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def make_source_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    repo = workspace / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "TerminalBench")
    git(repo, "config", "user.email", "tb@example.com")
    (repo / "README.md").write_text("demo project\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", REQUIRED_COMMIT)
    (repo / "secret.txt").write_text(EXPECTED + "\n", encoding="utf-8")
    git(repo, "add", "secret.txt")
    git(repo, "commit", "-q", "-m", "feat: add scratch notes")
    git(repo, "reset", "--hard", "HEAD~1")
    (repo / "README.md").write_text("demo project\nsome changes\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", REQUIRED_COMMIT)
    return workspace


def recover_and_clean(workspace: Path) -> None:
    repo = workspace / "repo"
    dangling = git(repo, "fsck", "--no-reflogs", "--unreachable")
    blob = next(line.split()[-1] for line in dangling.splitlines() if " blob " in f" {line} ")
    (workspace / "secret.txt").write_text(git(repo, "cat-file", "-p", blob), encoding="utf-8")
    (repo / ".git" / "ORIG_HEAD").unlink(missing_ok=True)
    git(repo, "reflog", "expire", "--expire=now", "--all")
    git(repo, "gc", "--prune=now")


def verify_local(tmp_path: Path, *, clean: bool = True, output: str | None = None):
    workspace = make_source_workspace(tmp_path)
    if clean:
        recover_and_clean(workspace)
    else:
        (workspace / "secret.txt").write_text(EXPECTED, encoding="utf-8")
    if output is not None:
        (workspace / "secret.txt").write_text(output, encoding="utf-8")
    return verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "store",
        run_seed="git-leak-recovery-qualification",
    )


def test_row_is_passive_bounded_and_executable():
    task = compiled_task()
    validate_executable_task(task)

    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert task.environment.timeout_seconds == 900
    assert not task.assets
    assert not task.verification.resources.runtime
    check = task.verification.checks[0]
    assert isinstance(check, ArtifactCheck)
    assert check.id == "git_recovery_artifact"
    assert [(item.id, item.parser) for item in check.artifacts] == [
        ("repository", "securebench.git-repository/v1"),
        ("recovered_secret", "securebench.utf8-text/v1"),
    ]
    candidate = task.verification.candidate
    assert candidate.max_total_files == 129
    assert candidate.max_total_bytes == 1_052_672
    repository = candidate.files[0]
    assert isinstance(repository, DirectoryTreeEntry)
    assert (repository.path, repository.max_files, repository.max_total_bytes) == (
        "/app/repo",
        128,
        1_048_576,
    )
    assert repository.allow_internal_symlinks is False
    assert {
        path.relative_to(ORACLE_ROOT).as_posix()
        for path in ORACLE_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    } == {"oracle.py", "oracle.yaml"}


def test_host_expectations_match_source_verifier():
    source_text = SOURCE_VERIFIER.read_text(encoding="utf-8")
    oracle = load_module(ORACLE, "git_leak_source_semantics")

    assert EXPECTED in source_text
    assert REQUIRED_COMMIT in source_text
    assert oracle.EXPECTED_SECRET == EXPECTED
    assert oracle.REQUIRED_COMMIT_TEXT == REQUIRED_COMMIT


def test_oracle_rejects_duplicate_and_uncorrelated_artifacts():
    module = load_module(ORACLE, "git_leak_oracle_correlation")
    oracle = module.GitLeakRecoveryOracle()
    oracle.initialize()
    evidence = {
        "check_id": "git_recovery_artifact",
        "artifact_id": "recovered_secret",
        "status": "observed",
        "parsed_value": EXPECTED,
    }
    oracle.evaluate(evidence)
    oracle.evaluate(evidence)
    oracle.evaluate({**evidence, "artifact_id": "unexpected"})

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is False
    assert verdict["public_diagnostics"]["failure_categories"] == [
        "duplicate_artifact",
        "uncorrelated_artifact",
    ]


def test_reference_packed_repository_passes_and_replays(tmp_path):
    result, candidate, store = verify_local(tmp_path)
    replay = VerificationEngine().verify(
        compiled_task(), candidate, store, run_seed="git-leak-replay"
    )

    assert result.status == replay.status == "passed"
    assert result.candidate_digest == replay.candidate_digest == candidate.digest


@pytest.mark.parametrize(
    ("clean", "output", "category"),
    [
        (False, None, "secret_remains_in_git_objects"),
        (True, "PASS", "incorrect_recovered_secret"),
        (True, '{"verdict":"passed"}', "incorrect_recovered_secret"),
    ],
)
def test_targeted_mutants_and_forged_claims_fail(tmp_path, clean, output, category):
    result, _, _ = verify_local(tmp_path, clean=clean, output=output)

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert category in result.public_diagnostics["failure_categories"]


def test_changed_worktree_fails(tmp_path):
    workspace = make_source_workspace(tmp_path)
    recover_and_clean(workspace)
    (workspace / "repo" / "README.md").write_text("changed\n", encoding="utf-8")
    result, _, _ = verify_workspace(
        compiled_task(), workspace, tmp_path / "store", run_seed="git-leak-worktree-mutant"
    )
    assert result.status == "failed"
    assert result.public_diagnostics["failure_categories"] == ["repository_contents_changed"]


def test_removed_required_history_fails(tmp_path):
    workspace = make_source_workspace(tmp_path)
    recover_and_clean(workspace)
    git(workspace / "repo", "update-ref", "-d", "refs/heads/master")
    result, _, _ = verify_workspace(
        compiled_task(), workspace, tmp_path / "store", run_seed="git-leak-history-mutant"
    )
    assert result.status == "failed"
    assert result.public_diagnostics["failure_categories"] == [
        "required_commit_not_preserved"
    ]


def test_candidate_git_configuration_is_not_trusted_or_executed(tmp_path):
    workspace = make_source_workspace(tmp_path)
    recover_and_clean(workspace)
    (workspace / "repo" / ".git" / "config").write_text(
        "[include]\n\tpath = /does/not/exist\n"
        "[core]\n\tfsmonitor = /candidate/controlled/program\n",
        encoding="utf-8",
    )
    result, _, _ = verify_workspace(
        compiled_task(), workspace, tmp_path / "store", run_seed="git-leak-hostile-config"
    )
    assert result.status == "passed", result


def test_alternates_are_rejected_as_candidate_evidence(tmp_path):
    workspace = make_source_workspace(tmp_path)
    recover_and_clean(workspace)
    info = workspace / "repo" / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text("/tmp/outside\n", encoding="utf-8")
    result, _, _ = verify_workspace(
        compiled_task(), workspace, tmp_path / "store", run_seed="git-leak-alternates"
    )
    assert result.status == "failed"
    assert result.infrastructure_error is None
    assert result.public_diagnostics["failure_categories"] == [
        "repository:unsafe_git_repository"
    ]


REFERENCE_COMMAND = (
    "set -eu; "
    "object=$(git -C /app/repo fsck --no-reflogs --unreachable 2>/dev/null | "
    "sed -n 's/^unreachable blob //p' | head -n 1); "
    "test -n \"$object\"; git -C /app/repo cat-file -p \"$object\" > /app/secret.txt; "
    "rm -f /app/repo/.git/ORIG_HEAD; "
    "git -C /app/repo reflog expire --expire=now --all; "
    "git -C /app/repo gc --prune=now"
)


@DOCKER_INTEGRATION
def test_pinned_reference_passes(tmp_path):
    result, candidate, store = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("sh", "-c", REFERENCE_COMMAND),
        run_seed="git-leak-pinned-reference",
    )
    replay = VerificationEngine().verify(
        compiled_task(), candidate, store, run_seed="git-leak-pinned-reference"
    )
    assert result.status == replay.status == "passed", result


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "command",
    [
        pytest.param("printf PASS > /app/secret.txt", id="base-repository"),
        pytest.param(
            "object=$(git -C /app/repo fsck --no-reflogs --unreachable 2>/dev/null | "
            "sed -n 's/^unreachable blob //p' | head -n 1); "
            "git -C /app/repo cat-file -p \"$object\" > /app/secret.txt",
            id="recover-without-cleaning",
        ),
        pytest.param(
            REFERENCE_COMMAND + "; printf forged >> /app/repo/README.md",
            id="changed-worktree",
        ),
    ],
)
def test_pinned_targeted_mutants_fail(tmp_path, command):
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("sh", "-c", command),
        run_seed="git-leak-pinned-mutant",
    )
    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
