from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from securebench.candidates import (
    CandidateCaptureError,
    CandidateReplayError,
    CandidateStore,
    CandidateStoreError,
    HostWorkspaceFilesystem,
    capture_file_bundle,
    capture_git_patch,
    replay_file_bundle,
    replay_git_patch,
)
from securebench.schemas.benchmark import FileBundleCandidate, GitPatchCandidate


BASELINE = "sha256:" + "1" * 64


def file_bundle_spec(*, tree=False, allow_internal_symlinks=False, max_total_bytes=4096):
    files = [
        {
            "id": "result",
            "path": "/app/result.json",
            "kind": "regular_file",
            "max_bytes": 1024,
        }
    ]
    max_files = 1
    if tree:
        files.append(
            {
                "id": "repository",
                "path": "/app/repository",
                "kind": "directory_tree",
                "max_files": 16,
                "max_total_bytes": 3072,
                "allow_internal_symlinks": allow_internal_symlinks,
            }
        )
        max_files = 17
    return FileBundleCandidate.model_validate(
        {
            "type": "file_bundle",
            "max_total_files": max_files,
            "max_total_bytes": max_total_bytes,
            "files": files,
        }
    )


def git_patch_spec(**updates):
    value = {
        "type": "git_patch",
        "max_patch_bytes": 1024 * 1024,
        "max_changed_files": 8,
        "max_changed_bytes": 1024 * 1024,
        "allow_paths": ["src/**"],
        "exclude_paths": [],
    }
    value.update(updates)
    return GitPatchCandidate.model_validate(value)


def git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def make_repository(root: Path) -> Path:
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.email", "securebench@example.invalid")
    git(root, "config", "user.name", "SecureBench")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("value = 1\n")
    (root / "securebench").mkdir()
    (root / "securebench" / "config.json").write_text("{}\n")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "baseline")
    return root


def test_file_bundle_capture_is_content_addressed_and_replayable(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "repository" / "nested").mkdir(parents=True)
    (workspace / "result.json").write_text('{"ok":true}\n')
    (workspace / "repository" / "README.md").write_text("candidate\n")
    executable = workspace / "repository" / "nested" / "run.sh"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    store = CandidateStore(tmp_path / "store")
    source = HostWorkspaceFilesystem(workspace, guest_root="/app")

    first = capture_file_bundle(
        source,
        file_bundle_spec(tree=True),
        store,
        baseline_digest=BASELINE,
    )
    second = capture_file_bundle(
        source,
        file_bundle_spec(tree=True),
        store,
        baseline_digest=BASELINE,
    )

    assert first.digest == second.digest
    target = tmp_path / "target"
    (target / "repository" / "stale").mkdir(parents=True)
    (target / "repository" / "stale" / "old.txt").write_text("remove me")
    replay_file_bundle(
        first,
        store,
        target,
        guest_root="/app",
        expected_baseline_digest=BASELINE,
    )
    assert (target / "result.json").read_text() == '{"ok":true}\n'
    assert (target / "repository" / "README.md").read_text() == "candidate\n"
    assert os.access(target / "repository" / "nested" / "run.sh", os.X_OK)
    assert not (target / "repository" / "stale").exists()


def test_file_bundle_rejects_escaping_symlink(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "repository").mkdir(parents=True)
    (workspace / "result.json").write_text("{}")
    (workspace / "repository" / "escape").symlink_to("../../secret")

    with pytest.raises(CandidateCaptureError, match="escapes tree"):
        capture_file_bundle(
            HostWorkspaceFilesystem(workspace, guest_root="/app"),
            file_bundle_spec(tree=True, allow_internal_symlinks=True),
            CandidateStore(tmp_path / "store"),
            baseline_digest=BASELINE,
        )


def test_file_bundle_accepts_explicit_safe_internal_symlink(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "repository" / "data").mkdir(parents=True)
    (workspace / "result.json").write_text("{}")
    (workspace / "repository" / "data" / "value.txt").write_text("ok")
    (workspace / "repository" / "current").symlink_to("data/value.txt")
    store = CandidateStore(tmp_path / "store")

    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        file_bundle_spec(tree=True, allow_internal_symlinks=True),
        store,
        baseline_digest=BASELINE,
    )
    target = tmp_path / "target"
    replay_file_bundle(
        candidate,
        store,
        target,
        guest_root="/app",
        expected_baseline_digest=BASELINE,
    )

    assert (target / "repository" / "current").is_symlink()
    assert (target / "repository" / "current").read_text() == "ok"


def test_file_bundle_enforces_byte_bounds_while_reading(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "result.json").write_bytes(b"x" * 2048)

    with pytest.raises(CandidateCaptureError, match="exceeds bound"):
        capture_file_bundle(
            HostWorkspaceFilesystem(workspace, guest_root="/app"),
            file_bundle_spec(),
            CandidateStore(tmp_path / "store"),
            baseline_digest=BASELINE,
        )


def test_candidate_store_detects_blob_tampering(tmp_path):
    store = CandidateStore(tmp_path / "store")
    digest = store.put_blob(b"trusted")
    hexadecimal = digest.removeprefix("sha256:")
    (store.blobs_root / hexadecimal[:2] / hexadecimal).write_bytes(b"tampered")

    with pytest.raises(CandidateStoreError, match="digest mismatch"):
        store.read_blob(digest)


def test_candidate_store_rejects_non_finite_manifest_data(tmp_path):
    store = CandidateStore(tmp_path / "store")

    with pytest.raises(CandidateStoreError, match="not canonical JSON"):
        store.put_candidate(
            "file_bundle",
            BASELINE,
            {"invalid_number": float("nan")},
        )


def test_file_bundle_replay_requires_exact_baseline(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "result.json").write_text("{}")
    store = CandidateStore(tmp_path / "store")
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        file_bundle_spec(),
        store,
        baseline_digest=BASELINE,
    )

    with pytest.raises(CandidateReplayError, match="baseline mismatch"):
        replay_file_bundle(
            candidate,
            store,
            tmp_path / "target",
            guest_root="/app",
            expected_baseline_digest="sha256:" + "2" * 64,
        )


def test_git_patch_capture_validates_then_replays(tmp_path):
    repository = make_repository(tmp_path / "repository")
    (repository / "src" / "app.py").write_text("value = 2\n")
    (repository / "src" / "new.py").write_text("new = True\n")
    git(repository, "add", "--intent-to-add", "src/new.py")
    patch = git(repository, "diff", "--binary", "--full-index", "HEAD")
    git(repository, "reset", "--hard", "--quiet", "HEAD")
    (repository / "src" / "new.py").unlink(missing_ok=True)
    store = CandidateStore(tmp_path / "store")

    candidate = capture_git_patch(
        patch,
        repository,
        git_patch_spec(),
        store,
        baseline_digest=BASELINE,
    )

    manifest = store.load_candidate(candidate.digest)
    assert manifest.payload["changed_files"] == ["src/app.py", "src/new.py"]
    replay = tmp_path / "replay"
    git(tmp_path, "clone", "--quiet", str(repository), str(replay))
    replay_git_patch(
        candidate,
        store,
        replay,
        expected_baseline_digest=BASELINE,
    )
    assert (replay / "src" / "app.py").read_text() == "value = 2\n"
    assert (replay / "src" / "new.py").read_text() == "new = True\n"


def test_git_patch_rejects_framework_protected_paths(tmp_path):
    repository = make_repository(tmp_path / "repository")
    (repository / "securebench" / "config.json").write_text('{"changed":true}\n')
    patch = git(repository, "diff", "--binary", "--full-index", "HEAD")
    git(repository, "reset", "--hard", "--quiet", "HEAD")

    with pytest.raises(CandidateCaptureError, match="protected or excluded"):
        capture_git_patch(
            patch,
            repository,
            git_patch_spec(allow_paths=[]),
            CandidateStore(tmp_path / "store"),
            baseline_digest=BASELINE,
        )


def test_empty_git_patch_is_a_replayable_candidate(tmp_path):
    repository = make_repository(tmp_path / "repository")
    store = CandidateStore(tmp_path / "store")

    candidate = capture_git_patch(
        b"",
        repository,
        git_patch_spec(),
        store,
        baseline_digest=BASELINE,
    )

    assert store.load_candidate(candidate.digest).payload["changed_files"] == []
