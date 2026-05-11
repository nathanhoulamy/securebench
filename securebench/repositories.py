"""Trusted repository preparation helpers for GitHub-style tasks."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from securebench.sandboxes import Sandbox
from securebench.tasks import GitHubPatchTask


class RepositoryPreparationError(ValueError):
    """Raised when SecureBench cannot prepare a repository checkout."""


@dataclass(frozen=True)
class PreparedRepository:
    """A repository checkout prepared in a sandbox-visible workspace."""

    path: Path
    repo_dir: str


class RepositoryPreparer(Protocol):
    """Prepare a fresh repository checkout for one task attempt."""

    def prepare(
        self,
        task: GitHubPatchTask,
        sandbox: Sandbox,
        *,
        repo_dir: str,
        timeout: float | None = None,
    ) -> PreparedRepository:
        """Populate ``repo_dir`` inside the sandbox workspace."""


class TrustedGitRepositoryPreparer:
    """Clone and checkout a Git repository from the trusted host side."""

    def prepare(
        self,
        task: GitHubPatchTask,
        sandbox: Sandbox,
        *,
        repo_dir: str,
        timeout: float | None = None,
    ) -> PreparedRepository:
        try:
            root = _sandbox_root(sandbox)
            target = _target_path(root, repo_dir)
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)

            clone = _run_git(["git", "clone", _repo_url(task.repo), str(target)], timeout=timeout)
            if clone.returncode != 0:
                raise RepositoryPreparationError(_format_failure("git clone", clone))

            checkout = _run_git(["git", "checkout", task.base_commit], cwd=target, timeout=timeout)
            if checkout.returncode != 0:
                raise RepositoryPreparationError(_format_failure("git checkout", checkout))
        except RepositoryPreparationError:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise RepositoryPreparationError(f"Repository preparation failed: {exc}") from exc

        return PreparedRepository(path=target, repo_dir=repo_dir)


def repo_url(repo: str) -> str:
    """Return a clone URL for GitHub shorthand or an explicit Git URL."""
    return _repo_url(repo)


def _sandbox_root(sandbox: Sandbox) -> Path:
    root = getattr(sandbox, "root", None)
    if root is None:
        raise RepositoryPreparationError(
            "Repository preparation requires a sandbox with a host-visible root"
        )
    return Path(root)


def _target_path(root: Path, repo_dir: str) -> Path:
    sandbox_path = PurePosixPath(repo_dir)
    if sandbox_path.is_absolute():
        sandbox_path = PurePosixPath(*sandbox_path.parts[1:])
    if ".." in sandbox_path.parts:
        raise RepositoryPreparationError(f"repo_dir may not escape sandbox root: {repo_dir}")
    return root.joinpath(*sandbox_path.parts)


def _repo_url(repo: str) -> str:
    if repo.startswith(("http://", "https://", "git@")):
        return repo
    return f"https://github.com/{repo}.git"


def _run_git(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _format_failure(operation: str, completed: subprocess.CompletedProcess[str]) -> str:
    stderr = completed.stderr.strip()
    stdout = completed.stdout.strip()
    details = stderr or stdout or f"exit code {completed.returncode}"
    return f"{operation} failed: {details}"
