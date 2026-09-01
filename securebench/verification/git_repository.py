"""Bounded, hook-free observations of a captured Git repository tree."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any

from securebench.sandboxes.base import run_bounded_subprocess
from securebench.verification.models import ParserRejected
from securebench.verification.parsers import BlobReader


MAX_GIT_OBJECTS = 512
MAX_GIT_OBJECT_BYTES = 256 * 1024
MAX_GIT_OBJECT_BYTES_TOTAL = 1024 * 1024
MAX_GIT_OBSERVATION_CHARACTERS = 1024 * 1024
GIT_TIMEOUT_SECONDS = 10
OBJECT_LINE = re.compile(r"^(?P<oid>[0-9a-f]{40}) (?P<kind>blob|commit|tag|tree) (?P<size>[0-9]+)$")


def git_repository_observation(
    tree: dict[str, Any],
    read_blob: BlobReader,
) -> dict[str, Any]:
    """Materialize bounded candidate bytes and return generic Git/object facts.

    Repository configuration is replaced before invoking trusted read-only Git
    commands. Symlinks, alternates, grafts, replace objects, hooks, filters, and
    ambient Git configuration therefore cannot influence the observation.
    """

    nodes = tree.get("nodes")
    if not isinstance(nodes, list):
        raise ParserRejected("invalid_git_repository", "Git repository tree is malformed")
    with tempfile.TemporaryDirectory(prefix="securebench-git-artifact-") as temporary:
        root = Path(temporary) / "repository"
        root.mkdir(mode=0o700)
        _materialize(nodes, root, read_blob)
        git_dir = root / ".git"
        if not git_dir.is_dir():
            raise ParserRejected("invalid_git_repository", "Candidate does not contain a Git repository")
        for forbidden in (
            git_dir / "objects" / "info" / "alternates",
            git_dir / "objects" / "info" / "http-alternates",
            git_dir / "info" / "grafts",
            git_dir / "commondir",
        ):
            if forbidden.exists():
                raise ParserRejected(
                    "unsafe_git_repository",
                    "Git repository uses an unsupported external object mechanism",
                )
        (git_dir / "config").write_text(
            "[core]\n\trepositoryformatversion = 0\n\tbare = false\n",
            encoding="utf-8",
        )
        env = _git_environment(root, git_dir, Path(temporary))

        object_lines = _git(root, env, "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype) %(objectsize)").splitlines()
        if len(object_lines) > MAX_GIT_OBJECTS:
            raise ParserRejected("git_repository_too_large", "Git repository contains too many objects")
        objects: list[dict[str, Any]] = []
        total_object_bytes = 0
        for line in object_lines:
            matched = OBJECT_LINE.fullmatch(line)
            if matched is None:
                raise ParserRejected("invalid_git_repository", "Git object inventory is malformed")
            size = int(matched.group("size"))
            if size > MAX_GIT_OBJECT_BYTES:
                raise ParserRejected("git_object_too_large", "Git repository contains an oversized object")
            total_object_bytes += size
            if total_object_bytes > MAX_GIT_OBJECT_BYTES_TOTAL:
                raise ParserRejected("git_repository_too_large", "Git repository object data exceeds its bound")
            objects.append(
                {
                    "oid": matched.group("oid"),
                    "kind": matched.group("kind"),
                    "size": size,
                }
            )

        reachable = {
            line.split(" ", 1)[0]
            for line in _git(root, env, "rev-list", "--objects", "--all").splitlines()
            if line
        }
        if any(not re.fullmatch(r"[0-9a-f]{40}", oid) for oid in reachable):
            raise ParserRejected("invalid_git_repository", "Git reachable-object inventory is malformed")

        observed_characters = 0
        for item in objects:
            content = _git(root, env, "cat-file", "-p", item["oid"])
            observed_characters += len(content)
            if observed_characters > MAX_GIT_OBSERVATION_CHARACTERS:
                raise ParserRejected("git_repository_too_large", "Git repository observation exceeds its bound")
            item["reachable"] = item["oid"] in reachable
            item["content"] = content

        return {
            "format": "git-repository",
            "objects": objects,
            "worktree": _worktree_observation(nodes),
        }


def _materialize(nodes: list[Any], root: Path, read_blob: BlobReader) -> None:
    directories: list[tuple[Path, int]] = []
    files: list[tuple[Path, int, str, int]] = []
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("path"), str):
            raise ParserRejected("invalid_git_repository", "Git repository tree is malformed")
        relative = PurePosixPath(node["path"])
        if relative.is_absolute() or ".." in relative.parts or str(relative) != node["path"]:
            raise ParserRejected("invalid_git_repository", "Git repository path is unsafe")
        target = root.joinpath(*relative.parts)
        kind = node.get("kind")
        if kind == "directory":
            directories.append((target, int(node.get("mode", 0))))
        elif kind == "regular_file":
            blob = node.get("blob")
            size = node.get("size")
            mode = node.get("mode")
            if not isinstance(blob, str) or not isinstance(size, int) or not isinstance(mode, int):
                raise ParserRejected("invalid_git_repository", "Git repository file metadata is malformed")
            files.append((target, mode, blob, size))
        else:
            raise ParserRejected("unsafe_git_repository", "Git repository may not contain symlinks")
    for target, mode in sorted(directories, key=lambda item: len(item[0].parts)):
        target.mkdir(mode=mode, parents=True, exist_ok=True)
    for target, mode, blob, size in files:
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        target.write_bytes(read_blob(blob, expected_size=size))
        target.chmod(mode)


def _git_environment(root: Path, git_dir: Path, home: Path) -> dict[str, str]:
    return {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_DIR": str(git_dir),
        "GIT_WORK_TREE": str(root),
        "GIT_NO_REPLACE_OBJECTS": "1",
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
    }


def _git(root: Path, env: dict[str, str], *arguments: str) -> str:
    result = run_bounded_subprocess(
        (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.attributesFile=/dev/null",
            "-c",
            "core.fsmonitor=false",
            *arguments,
        ),
        cwd=root,
        env=env,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.stdout_truncated or result.stderr_truncated:
        raise ParserRejected("git_output_too_large", "Git repository inspection output exceeds its bound")
    if result.returncode != 0:
        raise ParserRejected("invalid_git_repository", "Git repository could not be inspected")
    return result.stdout


def _worktree_observation(nodes: list[Any]) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict) or node.get("kind") != "regular_file":
            continue
        path = node.get("path")
        if not isinstance(path, str):
            continue
        parts = PurePosixPath(path).parts
        if any(part.startswith(".") for part in parts):
            continue
        observed.append(
            {
                "path": path,
                "size": node.get("size"),
                "blob": node.get("blob"),
            }
        )
    return sorted(observed, key=lambda item: item["path"])
