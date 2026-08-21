"""Fresh, integrity-checked reconstruction of filesystem-overlay Candidates."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from securebench.candidates.models import (
    CandidateCaptureError,
    CandidateReplayError,
    CandidateStoreError,
    StoredCandidate,
)
from securebench.candidates.overlay import (
    OverlayScanLimits,
    ScannedOverlayRoot,
    scan_overlay_roots,
)
from securebench.candidates.overlay_agent import materialize_overlay_image_roots
from securebench.candidates.store import CandidateStore
from securebench.schemas.benchmark import FilesystemOverlayCandidate
from securebench.tasks import BenchmarkTask
from securebench.workspaces.overlay_quota import (
    OverlayQuotaWorkspace,
    OverlayWorkspaceError,
)


WorkspaceFactory = Callable[..., OverlayQuotaWorkspace]
BaselineMaterializer = Callable[..., dict[str, ScannedOverlayRoot]]


@dataclass
class ReconstructedOverlay:
    """One fresh replay, owned until its Evaluation or observation is complete."""

    workspace: OverlayQuotaWorkspace
    roots: dict[str, Path]

    def close(self) -> None:
        self.workspace.close()


@dataclass(frozen=True)
class OverlayReplayBackend:
    """Reviewed quota backend settings used for every fresh reconstruction."""

    storage_root: Path
    capacity_bytes: int
    scan_limits: OverlayScanLimits = OverlayScanLimits()
    workspace_factory: WorkspaceFactory = OverlayQuotaWorkspace.create
    materializer: BaselineMaterializer = materialize_overlay_image_roots

    def reconstruct(
        self,
        task: BenchmarkTask,
        candidate: StoredCandidate,
        store: CandidateStore,
    ) -> ReconstructedOverlay:
        spec = task.verification.candidate
        if not isinstance(spec, FilesystemOverlayCandidate):
            raise CandidateReplayError(
                "overlay reconstruction requires a filesystem_overlay task"
            )
        workspace: OverlayQuotaWorkspace | None = None
        try:
            workspace = self.workspace_factory(
                storage_root=self.storage_root,
                capacity_bytes=self.capacity_bytes,
                include_roots=spec.include_roots,
            )
            if workspace.include_roots != spec.include_roots:
                raise CandidateReplayError("overlay workspace roots do not match the task")
            baseline = self.materializer(
                task.environment.image,
                workspace,
                scan_limits=self.scan_limits,
            )
            roots = workspace.host_roots()
            replay_filesystem_overlay(
                candidate,
                store,
                roots,
                spec=spec,
                expected_baseline_digest=task.baseline_digest,
                baseline=baseline,
                scan_limits=self.scan_limits,
            )
            return ReconstructedOverlay(workspace=workspace, roots=roots)
        except BaseException:
            if workspace is not None:
                try:
                    workspace.close()
                except OverlayWorkspaceError as cleanup_exc:
                    raise CandidateReplayError(
                        "failed to clean up rejected overlay reconstruction"
                    ) from cleanup_exc
            raise


def replay_filesystem_overlay(
    candidate: StoredCandidate,
    store: CandidateStore,
    roots: dict[str, Path],
    *,
    spec: FilesystemOverlayCandidate,
    expected_baseline_digest: str,
    baseline: dict[str, ScannedOverlayRoot] | None = None,
    scan_limits: OverlayScanLimits = OverlayScanLimits(),
) -> None:
    """Apply one validated overlay and prove the reconstructed final-state digest."""
    try:
        manifest = store.load_candidate(candidate.digest)
    except CandidateStoreError as exc:
        raise CandidateReplayError("filesystem_overlay Candidate storage is invalid") from exc
    if (
        manifest.type != "filesystem_overlay"
        or candidate.type != "filesystem_overlay"
        or manifest.baseline_digest != expected_baseline_digest
        or candidate.baseline_digest != expected_baseline_digest
    ):
        raise CandidateReplayError("filesystem_overlay Candidate binding is invalid")
    payload = manifest.payload
    root_rows = payload["roots"]
    changes = payload["changes"]
    if (
        payload["changed_paths"] > spec.max_changed_paths
        or payload["changed_bytes"] > spec.max_changed_bytes
    ):
        raise CandidateReplayError("filesystem_overlay Candidate exceeds the row bounds")
    if not spec.allow_internal_symlinks and any(
        change["kind"] == "symlink" for change in changes
    ):
        raise CandidateReplayError("filesystem_overlay Candidate contains disabled symlinks")
    expected_roots = tuple(spec.include_roots)
    if set(roots) != set(expected_roots):
        raise CandidateReplayError("filesystem_overlay replay roots do not match the task")
    if [row["path"] for row in root_rows] != sorted(
        expected_roots, key=lambda value: value.encode("utf-8")
    ):
        raise CandidateReplayError("filesystem_overlay manifest roots do not match the task")
    try:
        actual_baseline = baseline or scan_overlay_roots(
            expected_roots, roots, limits=scan_limits, label="replay baseline"
        )
    except CandidateCaptureError as exc:
        raise CandidateReplayError("filesystem_overlay baseline could not be verified") from exc
    _require_root_state(root_rows, actual_baseline, prefix="baseline")

    deletions = [change for change in changes if change["kind"] == "absent"]
    final_nodes = [change for change in changes if change["kind"] != "absent"]
    for change in sorted(deletions, key=_deepest_first):
        _remove_target(roots[change["root"]], change["path"], must_exist=True)
    for change in sorted(final_nodes, key=_shallowest_first):
        _remove_type_conflict(roots[change["root"]], change)
    directories = [change for change in final_nodes if change["kind"] == "directory"]
    files = [change for change in final_nodes if change["kind"] == "regular_file"]
    links = [change for change in final_nodes if change["kind"] == "symlink"]
    for change in sorted(directories, key=_shallowest_first):
        _make_directory(roots[change["root"]], change["path"])
    for change in files:
        _write_file_atomically(roots[change["root"]], change, store)
    for change in links:
        _make_symlink(roots[change["root"]], change["path"], change["target"])
    for change in sorted(directories, key=_deepest_first):
        target = _target(
            roots[change["root"]],
            change["path"],
            require_parent=True,
        )
        try:
            target.chmod(0o755, follow_symlinks=False)
        except OSError as exc:
            raise CandidateReplayError(
                "filesystem_overlay directory mode could not be applied"
            ) from exc

    try:
        final = scan_overlay_roots(
            expected_roots, roots, limits=scan_limits, label="replayed final"
        )
    except CandidateCaptureError as exc:
        raise CandidateReplayError("filesystem_overlay final state could not be verified") from exc
    _require_root_state(root_rows, final, prefix="final")


def overlay_host_path(roots: dict[str, Path], source_path: str) -> tuple[Path, str]:
    """Map one absolute overlay artifact path to its fresh host root and relative path."""
    source = PurePosixPath(source_path)
    matches = [root for root in roots if source.is_relative_to(PurePosixPath(root))]
    if len(matches) != 1:
        raise CandidateReplayError("overlay artifact path does not select exactly one root")
    root = matches[0]
    relative = source.relative_to(PurePosixPath(root))
    if not relative.parts:
        host_root = roots[root]
        return host_root.parent, host_root.name
    return roots[root], str(relative)


def _require_root_state(
    rows: list[dict[str, object]],
    scans: dict[str, ScannedOverlayRoot],
    *,
    prefix: str,
) -> None:
    for row in rows:
        path = row["path"]
        assert isinstance(path, str)
        scanned = scans.get(path)
        if scanned is None or (
            scanned.digest != row[f"{prefix}_tree_digest"]
            or scanned.entries != row[f"{prefix}_entries"]
            or scanned.bytes != row[f"{prefix}_bytes"]
        ):
            raise CandidateReplayError(f"filesystem_overlay {prefix} root mismatch")


def _deepest_first(change: dict[str, object]) -> tuple[int, bytes, bytes]:
    path = str(change["path"])
    return (-len(PurePosixPath(path).parts), str(change["root"]).encode(), path.encode())


def _shallowest_first(change: dict[str, object]) -> tuple[int, bytes, bytes]:
    path = str(change["path"])
    return (len(PurePosixPath(path).parts), str(change["root"]).encode(), path.encode())


def _target(root: Path, relative: str, *, require_parent: bool) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise CandidateReplayError("filesystem_overlay replay path is unsafe")
    current = root
    parts = path.parts[:-1]
    for part in parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError as exc:
            if require_parent:
                raise CandidateReplayError("filesystem_overlay replay parent is missing") from exc
            break
        except OSError as exc:
            raise CandidateReplayError(
                "filesystem_overlay replay parent is inaccessible"
            ) from exc
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise CandidateReplayError("filesystem_overlay replay parent is not a real directory")
    return root.joinpath(*path.parts)


def _remove_target(root: Path, relative: str, *, must_exist: bool) -> None:
    target = _target(root, relative, require_parent=True)
    try:
        info = target.lstat()
    except FileNotFoundError as exc:
        if must_exist:
            raise CandidateReplayError("filesystem_overlay deletion target is missing") from exc
        return
    except OSError as exc:
        raise CandidateReplayError("filesystem_overlay replay target is inaccessible") from exc
    try:
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            target.rmdir()
        else:
            target.unlink()
    except OSError as exc:
        raise CandidateReplayError("filesystem_overlay replay target could not be removed") from exc


def _remove_type_conflict(root: Path, change: dict[str, object]) -> None:
    target = _target(root, str(change["path"]), require_parent=False)
    try:
        info = target.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise CandidateReplayError(
            "filesystem_overlay replay target is inaccessible"
        ) from exc
    wanted = str(change["kind"])
    actual = (
        "directory"
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
        else "regular_file"
        if stat.S_ISREG(info.st_mode)
        else "symlink"
        if stat.S_ISLNK(info.st_mode)
        else "unsupported"
    )
    if actual != wanted or wanted == "symlink":
        _remove_target(root, str(change["path"]), must_exist=True)


def _make_directory(root: Path, relative: str) -> None:
    target = _target(root, relative, require_parent=True)
    try:
        target.mkdir(mode=0o755)
    except FileExistsError:
        try:
            info = target.lstat()
        except OSError as exc:
            raise CandidateReplayError(
                "filesystem_overlay directory target is inaccessible"
            ) from exc
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise CandidateReplayError("filesystem_overlay directory target has wrong type")
    except OSError as exc:
        raise CandidateReplayError("filesystem_overlay directory could not be created") from exc


def _write_file_atomically(
    root: Path,
    change: dict[str, object],
    store: CandidateStore,
) -> None:
    target = _target(root, str(change["path"]), require_parent=True)
    descriptor: int | None = None
    temporary: Path | None = None
    digest = hashlib.sha256()
    total = 0
    try:
        descriptor, name = tempfile.mkstemp(prefix=".securebench-replay-", dir=target.parent)
        temporary = Path(name)
        for chunk in change["chunks"]:  # type: ignore[union-attr]
            content = store.read_blob(chunk["digest"], expected_size=chunk["size"])
            digest.update(content)
            total += len(content)
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short overlay replay write")
                view = view[written:]
        if (
            total != change["size"]
            or "sha256:" + digest.hexdigest() != change["digest"]
        ):
            raise CandidateReplayError("filesystem_overlay file content does not match manifest")
        os.fchmod(descriptor, int(change["mode"]))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, target)
        temporary = None
    except CandidateReplayError:
        raise
    except (CandidateStoreError, OSError, TypeError) as exc:
        raise CandidateReplayError("filesystem_overlay file could not be replayed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _make_symlink(root: Path, relative: str, link_target: str) -> None:
    target = _target(root, relative, require_parent=True)
    # Stored-manifest validation already proves lexical containment. Recheck at the sink.
    stack = list(PurePosixPath(relative).parent.parts)
    candidate = PurePosixPath(link_target)
    if candidate.is_absolute() or "\\" in link_target or "\x00" in link_target:
        raise CandidateReplayError("filesystem_overlay symlink target is unsafe")
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not stack:
                raise CandidateReplayError("filesystem_overlay symlink escapes its root")
            stack.pop()
        else:
            stack.append(part)
    try:
        target.symlink_to(link_target)
    except OSError as exc:
        raise CandidateReplayError("filesystem_overlay symlink could not be created") from exc
