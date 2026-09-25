"""Pytest plugin: record every fixed candidate the qualification tests build.

Load it with ``-p tools.native_baseline.candidate_recorder`` and set
``CAMPAIGN_CANDIDATE_DIR``. It does not change test behaviour; it wraps
candidate capture, the candidate store and the verification engine, and writes
what they saw, tagged with the running test's node id:

    <dir>/records.jsonl          one JSON event per capture / verify
    <dir>/blobs/<sha256>         candidate bytes (patches, bundle files)
    <dir>/trees/<sha256>.tar     declared paths of a file_bundle workspace whose
                                 capture was rejected (symlinks preserved)

For git_patch captures it also stores the *raw* workspace diff against the
base commit (before SecureBench drops ``exclude_paths``), because that is what
an upstream verifier would receive from the same workspace.

The recorded in-test verdicts are a cross-check only. Phase 1's SecureBench
verdict comes from replaying each candidate with ``harness.type: command``.
"""

from __future__ import annotations

import functools
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_CURRENT = {"nodeid": None}
_DIR: Path | None = None


def _out() -> Path:
    assert _DIR is not None
    return _DIR


def _put_blob(content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    path = _out() / "blobs" / digest
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return digest


def _event(kind: str, **fields) -> None:
    record = {"kind": kind, "nodeid": _CURRENT["nodeid"], "time": time.time(), **fields}
    line = json.dumps(record, sort_keys=True, default=str)
    with _LOCK:
        with (_out() / "records.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _raw_git_diff(workspace: Path, base_commit: str) -> bytes | None:
    """Full diff of the workspace (tracked + untracked) against base, via a temp index."""
    with tempfile.TemporaryDirectory(prefix="recorder-index-") as temporary:
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            "GIT_INDEX_FILE": str(Path(temporary) / "index"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        git = ["git", "-c", "safe.directory=*", "-C", str(workspace)]
        steps = [
            git + ["read-tree", base_commit],
            git + ["add", "-A", "--", "."],
        ]
        for step in steps:
            if subprocess.run(step, env=env, capture_output=True).returncode != 0:
                return None
        completed = subprocess.run(
            git + ["diff", "--cached", "--binary", "--no-renames", base_commit],
            env=env,
            capture_output=True,
        )
        return completed.stdout if completed.returncode == 0 else None


def _wrap_capture_git_patch_workspace(original):
    @functools.wraps(original)
    def wrapper(workspace, baseline_repo, spec, store, *args, **kwargs):
        base_commit = kwargs.get("base_commit")
        try:
            stored = original(workspace, baseline_repo, spec, store, *args, **kwargs)
        except Exception as exc:
            raw = _raw_git_diff(Path(workspace), base_commit) if base_commit else None
            _event(
                "capture_rejected",
                candidate_type="git_patch",
                error=f"{type(exc).__name__}: {exc}"[:2000],
                raw_patch_blob=None if raw is None else _put_blob(raw),
            )
            raise
        raw = _raw_git_diff(Path(workspace), base_commit) if base_commit else None
        _event(
            "capture",
            candidate_type="git_patch",
            candidate_digest=stored.digest,
            raw_patch_blob=None if raw is None else _put_blob(raw),
            base_commit=base_commit,
        )
        return stored

    wrapper.__recorder_original__ = original
    return wrapper


def _tar_declared(filesystem, spec) -> str | None:
    root = getattr(filesystem, "root", None) or getattr(filesystem, "_root", None)
    guest_root = getattr(filesystem, "guest_root", None) or getattr(filesystem, "_guest_root", "/")
    if root is None:
        return None
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for declared in spec.files:
            relative = os.path.relpath(declared.path, guest_root)
            host = Path(root) / relative
            if host.exists() or host.is_symlink():
                archive.add(str(host), arcname=declared.path.lstrip("/"), recursive=True)
    content = buffer.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    path = _out() / "trees" / f"{digest}.tar"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return digest


def _wrap_capture_file_bundle(original):
    @functools.wraps(original)
    def wrapper(filesystem, spec, store, *args, **kwargs):
        try:
            stored = original(filesystem, spec, store, *args, **kwargs)
        except Exception as exc:
            try:
                tree = _tar_declared(filesystem, spec)
            except Exception as tar_exc:  # recording must never break the test
                tree = f"unrecorded: {tar_exc}"
            _event(
                "capture_rejected",
                candidate_type="file_bundle",
                error=f"{type(exc).__name__}: {exc}"[:2000],
                tree=tree,
            )
            raise
        _event("capture", candidate_type="file_bundle", candidate_digest=stored.digest)
        return stored

    wrapper.__recorder_original__ = original
    return wrapper


def _wrap_put_candidate(original):
    @functools.wraps(original)
    def wrapper(self, candidate_type, baseline_digest, payload, *args, **kwargs):
        stored = original(self, candidate_type, baseline_digest, payload, *args, **kwargs)
        blobs = {}
        store = getattr(self, "store", self)
        for digest in _payload_blob_digests(payload):
            try:
                blobs[digest] = _put_blob(store.read_blob(digest))
            except Exception as exc:  # pragma: no cover - diagnostic only
                blobs[digest] = f"unreadable: {exc}"
        _event(
            "put_candidate",
            candidate_type=str(candidate_type),
            candidate_digest=stored.digest,
            baseline_digest=baseline_digest,
            payload=payload,
            blobs=blobs,
        )
        return stored

    return wrapper


def _payload_blob_digests(payload) -> list[str]:
    found = []

    def walk(value, key=None):
        if isinstance(value, dict):
            for inner_key, inner in value.items():
                walk(inner, inner_key)
        elif isinstance(value, list):
            for inner in value:
                walk(inner, key)
        elif isinstance(value, str) and key in {"blob", "digest", "patch_blob", "content_digest", "sha256"}:
            found.append(value)

    walk(payload)
    return found


def _wrap_verify(original, kind):
    @functools.wraps(original)
    def wrapper(self, task, *args, **kwargs):
        result = original(self, task, *args, **kwargs)
        candidate = args[0] if args and kind == "verify" else kwargs.get("candidate")
        _event(
            kind,
            task_id=getattr(task, "id", None),
            candidate_digest=getattr(candidate, "digest", None) if candidate is not None else None,
            code=kwargs.get("code"),
            status=str(getattr(result, "status", None)),
            passed=getattr(result, "passed", None),
            score=getattr(result, "score", None),
        )
        return result

    return wrapper


def _rebind(original, replacement) -> None:
    """Point every already-imported alias of ``original`` at ``replacement``."""
    for module in list(sys.modules.values()):
        namespace = getattr(module, "__dict__", None)
        if not namespace:
            continue
        for name, value in list(namespace.items()):
            if value is original:
                setattr(module, name, replacement)


_ORIGINALS: dict[str, object] = {}
_REPLACEMENTS: dict[str, object] = {}


def pytest_configure(config):
    global _DIR
    target = os.environ.get("CAMPAIGN_CANDIDATE_DIR")
    if not target:
        raise RuntimeError("candidate_recorder requires CAMPAIGN_CANDIDATE_DIR")
    _DIR = Path(target)
    _DIR.mkdir(parents=True, exist_ok=True)

    from securebench.candidates import capture
    from securebench.candidates.store import CandidateStore, CandidateStoreTransaction
    from securebench.verification.artifacts import VerificationEngine

    for name, factory in (
        ("capture_git_patch_workspace", _wrap_capture_git_patch_workspace),
        ("capture_file_bundle", _wrap_capture_file_bundle),
    ):
        original = getattr(capture, name)
        replacement = factory(original)
        _ORIGINALS[name] = original
        _REPLACEMENTS[name] = replacement
        _rebind(original, replacement)

    CandidateStore.put_candidate = _wrap_put_candidate(CandidateStore.put_candidate)
    CandidateStoreTransaction.put_candidate = _wrap_put_candidate(
        CandidateStoreTransaction.put_candidate
    )
    VerificationEngine.verify = _wrap_verify(VerificationEngine.verify, "verify")
    VerificationEngine.verify_candidate_error = _wrap_verify(
        VerificationEngine.verify_candidate_error, "verify_candidate_error"
    )


def pytest_collection_finish(session):
    # Test modules imported during collection bound the original functions.
    for name, original in _ORIGINALS.items():
        _rebind(original, _REPLACEMENTS[name])


def pytest_runtest_setup(item):
    _CURRENT["nodeid"] = item.nodeid


def pytest_runtest_logreport(report):
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        _event("test_outcome", when=report.when, outcome=report.outcome)


def pytest_runtest_teardown(item):
    _CURRENT["nodeid"] = item.nodeid
