"""Trusted Git repository identity and command helpers."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


CANONICAL_COMMIT_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
GIT_CONFIG_OPTIONS = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.untrackedCache=false",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.safecrlf=false",
    "-c",
    "core.filemode=true",
    "-c",
    "core.symlinks=true",
    "-c",
    "diff.external=",
)


class GitRepositoryError(ValueError):
    """A repository does not satisfy the trusted baseline contract."""


def canonical_base_commit(value: object) -> str:
    """Return a full lowercase Git object ID or reject the value."""
    if not isinstance(value, str) or CANONICAL_COMMIT_PATTERN.fullmatch(value) is None:
        raise GitRepositoryError("base_commit must be a full lowercase Git object ID")
    return value


def validate_clean_repository(repository: str | Path, expected_commit: str) -> str:
    """Require a non-symlink Git repository at one exact clean commit."""
    expected = canonical_base_commit(expected_commit)
    root = Path(repository).resolve()
    git_directory = root / ".git"
    if not root.is_dir() or git_directory.is_symlink() or not git_directory.is_dir():
        raise GitRepositoryError("repository baseline must contain a .git directory")
    head = run_git_bytes(
        ["rev-parse", "--verify", "HEAD^{commit}"],
        cwd=root,
        context="resolve repository baseline commit",
    ).decode("ascii", errors="strict").strip()
    if head != expected:
        raise GitRepositoryError(
            f"repository baseline commit mismatch: expected {expected}, got {head}"
        )
    status = run_git_bytes(
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        context="inspect repository baseline state",
    )
    if status:
        raise GitRepositoryError("repository baseline must be clean")
    return head


def git_environment() -> dict[str, str]:
    """Return an environment that disables host-level Git configuration."""
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    })
    return environment


def git_command(arguments: list[str] | tuple[str, ...]) -> list[str]:
    return ["git", *GIT_CONFIG_OPTIONS, *arguments]


def run_git_bytes(
    arguments: list[str] | tuple[str, ...],
    *,
    cwd: Path | None = None,
    context: str,
    stdin: bytes | None = None,
) -> bytes:
    completed = subprocess.run(
        git_command(arguments),
        cwd=cwd,
        env=git_environment(),
        input=stdin,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        error = completed.stderr[:65536].decode("utf-8", errors="replace").strip()
        raise GitRepositoryError(f"failed to {context}: {error}")
    return completed.stdout
