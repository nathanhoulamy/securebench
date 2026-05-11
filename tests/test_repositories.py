from pathlib import Path
from types import SimpleNamespace

import pytest

from securebench.repositories import RepositoryPreparationError, TrustedGitRepositoryPreparer, repo_url
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import task_from_spec


class RootedSandbox(Sandbox):
    def __init__(self, root):
        self.root = root

    def run(self, command, *, workdir=None, timeout=None):
        return CommandResult(tuple(command), 0, "", "")

    def write_file(self, path, content):
        pass

    def read_file(self, path):
        return ""

    def extract_file(self, path):
        return b""


def make_task():
    return task_from_spec(
        {
            "id": "example__repo-1",
            "benchmark_id": "example",
            "task_type": "github_patch",
            "resources": {
                "repo": {"value": "example/repo", "visibility": "public"},
                "base_commit": {"value": "abc123", "visibility": "public"},
                "instructions": {"value": "Fix the issue.", "visibility": "public"},
            },
        }
    )


def test_repo_url_expands_github_shorthand():
    assert repo_url("example/repo") == "https://github.com/example/repo.git"
    assert repo_url("https://example.com/repo.git") == "https://example.com/repo.git"


def test_trusted_git_repository_preparer_clones_and_checkouts_in_sandbox_root(monkeypatch, tmp_path):
    seen = []

    def fake_run(command, **kwargs):
        seen.append((command, kwargs))
        if command[:2] == ["git", "clone"]:
            Path(command[-1]).mkdir(parents=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    prepared = TrustedGitRepositoryPreparer().prepare(
        make_task(),
        RootedSandbox(tmp_path),
        repo_dir="repo",
        timeout=7,
    )

    assert prepared.path == tmp_path / "repo"
    assert seen[0][0] == ["git", "clone", "https://github.com/example/repo.git", str(tmp_path / "repo")]
    assert seen[0][1]["timeout"] == 7
    assert seen[1][0] == ["git", "checkout", "abc123"]
    assert seen[1][1]["cwd"] == tmp_path / "repo"


def test_trusted_git_repository_preparer_rejects_escaping_repo_dir(tmp_path):
    with pytest.raises(RepositoryPreparationError, match="repo_dir may not escape"):
        TrustedGitRepositoryPreparer().prepare(make_task(), RootedSandbox(tmp_path), repo_dir="../repo")


def test_trusted_git_repository_preparer_requires_host_visible_sandbox_root():
    with pytest.raises(RepositoryPreparationError, match="host-visible root"):
        TrustedGitRepositoryPreparer().prepare(make_task(), object(), repo_dir="repo")


def test_trusted_git_repository_preparer_wraps_git_subprocess_errors(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RepositoryPreparationError, match="Repository preparation failed"):
        TrustedGitRepositoryPreparer().prepare(make_task(), RootedSandbox(tmp_path), repo_dir="repo")
