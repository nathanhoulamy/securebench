from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import securebench.candidates.overlay as overlay_module
from securebench.candidates import (
    CandidateCaptureError,
    CandidateReplayError,
    CandidateStore,
    CandidateStoreError,
    OverlayScanLimits,
    capture_filesystem_overlay,
    scan_overlay_root,
    replay_filesystem_overlay,
    scan_overlay_roots,
)
from securebench.candidates.overlay import OVERLAY_CHUNK_BYTES
from securebench.candidates.store import CandidateStoreTransaction
from securebench.schemas.benchmark import FilesystemOverlayCandidate


BASELINE = "sha256:" + "1" * 64


@pytest.fixture(autouse=True)
def ignore_host_macos_provenance(monkeypatch: pytest.MonkeyPatch):
    # Phase 4 production is Linux-only; macOS automatically adds
    # com.apple.provenance to test-created files.
    if os.uname().sysname == "Darwin":
        monkeypatch.setattr(overlay_module, "_has_extended_metadata", lambda path: False)


def overlay_spec(**updates: object) -> FilesystemOverlayCandidate:
    value: dict[str, object] = {
        "type": "filesystem_overlay",
        "include_roots": ["/app"],
        "max_changed_paths": 100,
        "max_changed_bytes": 16 * 1024 * 1024,
        "allow_internal_symlinks": False,
    }
    value.update(updates)
    return FilesystemOverlayCandidate.model_validate(value)


def local_limits(**updates: object) -> OverlayScanLimits:
    value: dict[str, object] = {
        "required_uid": os.getuid(),
        "required_gid": os.getgid(),
    }
    value.update(updates)
    return OverlayScanLimits(**value)


def root_pair(tmp_path: Path) -> tuple[Path, Path]:
    baseline = tmp_path / "baseline"
    (baseline / "removed" / "nested").mkdir(parents=True)
    (baseline / "unchanged.txt").write_text("same\n")
    (baseline / "changed.txt").write_text("before\n")
    (baseline / "removed" / "one.txt").write_text("one\n")
    (baseline / "removed" / "nested" / "two.txt").write_text("two\n")
    final = tmp_path / "final"
    shutil.copytree(baseline, final)
    return baseline, final


def capture(
    baseline: Path,
    final: Path,
    store: CandidateStore,
    *,
    spec: FilesystemOverlayCandidate | None = None,
):
    return capture_filesystem_overlay(
        {"/app": baseline},
        {"/app": final},
        spec or overlay_spec(),
        store,
        baseline_digest=BASELINE,
        scan_limits=local_limits(),
    )


def test_overlay_capture_is_deterministic_canonical_and_chunked(tmp_path: Path):
    baseline, final = root_pair(tmp_path)
    shutil.rmtree(final / "removed")
    (final / "changed.txt").write_text("after\n")
    (final / "bin").mkdir()
    executable = final / "bin" / "tool"
    executable.write_bytes(b"x" * (OVERLAY_CHUNK_BYTES + 17))
    executable.chmod(0o700)
    store = CandidateStore(tmp_path / "store")

    first = capture(baseline, final, store)
    second = capture(baseline, final, store)

    assert first.digest == second.digest
    manifest = store.load_candidate(first.digest)
    changes = manifest.payload["changes"]
    keys = [(row["root"].encode(), row["path"].encode()) for row in changes]
    assert keys == sorted(keys)
    assert [row["path"] for row in changes if row["kind"] == "absent"] == [
        "removed",
        "removed/nested",
        "removed/nested/two.txt",
        "removed/one.txt",
    ]
    stored_file = next(row for row in changes if row["path"] == "bin/tool")
    assert stored_file["mode"] == 0o755
    assert [chunk["size"] for chunk in stored_file["chunks"]] == [
        OVERLAY_CHUNK_BYTES,
        17,
    ]
    assert manifest.payload["changed_paths"] == len(changes)


def test_overlay_load_detects_corrupt_chunk(tmp_path: Path):
    baseline, final = root_pair(tmp_path)
    (final / "changed.txt").write_text("after\n")
    store = CandidateStore(tmp_path / "store")
    candidate = capture(baseline, final, store)
    payload = store.load_candidate(candidate.digest).payload
    chunk_digest = next(
        row for row in payload["changes"] if row["kind"] == "regular_file"
    )["chunks"][0]["digest"]
    store._blob_path(chunk_digest).write_bytes(b"corrupt")

    with pytest.raises(CandidateStoreError, match="blob (digest|size) mismatch|exceeds"):
        store.load_candidate(candidate.digest)


def test_overlay_deletion_bomb_is_charged_per_descendant(tmp_path: Path):
    baseline, final = root_pair(tmp_path)
    shutil.rmtree(final / "removed")
    store = CandidateStore(tmp_path / "store")

    with pytest.raises(CandidateCaptureError, match="max_changed_paths"):
        capture(
            baseline,
            final,
            store,
            spec=overlay_spec(max_changed_paths=2),
        )
    assert not any(store.blobs_root.rglob("*"))
    assert not any(store.candidates_root.rglob("*"))
    assert not any(store.transactions_root.iterdir())


@pytest.mark.parametrize(
    ("limits", "message"),
    [
        ({"max_entries": 2}, "entry bound"),
        ({"max_bytes": 4}, "byte bound"),
    ],
)
def test_overlay_scan_rejects_oversized_trees(tmp_path: Path, limits, message):
    root = tmp_path / "root"
    root.mkdir()
    for index in range(3):
        (root / f"{index}.txt").write_text("data")

    with pytest.raises(CandidateCaptureError, match=message):
        scan_overlay_root("/app", root, limits=local_limits(**limits))


def test_overlay_scan_rejects_excessive_depth(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    current = root
    for _ in range(129):
        current = current / "d"
        current.mkdir()

    with pytest.raises(CandidateCaptureError, match="path exceeds"):
        scan_overlay_root("/app", root, limits=local_limits())


def test_overlay_scan_rejects_hardlinks(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    first = root / "first"
    first.write_text("same inode")
    os.link(first, root / "second")

    with pytest.raises(CandidateCaptureError, match="hardlink"):
        scan_overlay_root("/app", root, limits=local_limits())


def test_overlay_scan_rejects_special_files(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    os.mkfifo(root / "pipe")

    with pytest.raises(CandidateCaptureError, match="special file"):
        scan_overlay_root("/app", root, limits=local_limits())


def test_overlay_scan_rejects_unsupported_mode_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "root"
    root.mkdir()
    path = root / "setuid"
    path.write_text("data")
    current = path.lstat()
    unsupported = SimpleNamespace(
        st_uid=current.st_uid,
        st_gid=current.st_gid,
        st_mode=current.st_mode | stat.S_ISUID,
        st_nlink=current.st_nlink,
        st_flags=0,
    )
    monkeypatch.setattr(overlay_module, "_has_extended_metadata", lambda candidate: False)

    with pytest.raises(CandidateCaptureError, match="unsupported mode"):
        overlay_module._validate_metadata(
            path,
            unsupported,
            local_limits(),
            is_root=False,
        )


def test_overlay_scan_rejects_extended_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "root"
    root.mkdir()
    path = root / "file"
    path.write_text("data")
    monkeypatch.setattr(
        overlay_module,
        "_has_extended_metadata",
        lambda candidate: candidate == path,
    )

    with pytest.raises(CandidateCaptureError, match="xattrs or ACLs"):
        scan_overlay_root("/app", root, limits=local_limits())


def test_overlay_rejects_cross_tree_portable_alias(tmp_path: Path):
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    baseline.mkdir()
    final.mkdir()
    (baseline / "Config").write_text("before")
    (final / "config").write_text("after")

    with pytest.raises(CandidateCaptureError, match="paths alias"):
        capture(baseline, final, CandidateStore(tmp_path / "store"))


def test_overlay_rejects_changed_symlink_escape(tmp_path: Path):
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    baseline.mkdir()
    final.mkdir()
    (final / "escape").symlink_to("../../outside")

    with pytest.raises(CandidateCaptureError, match="escapes"):
        capture(
            baseline,
            final,
            CandidateStore(tmp_path / "store"),
            spec=overlay_spec(allow_internal_symlinks=True),
        )


def test_overlay_captures_only_opted_in_internal_symlinks(tmp_path: Path):
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    baseline.mkdir()
    final.mkdir()
    (final / "target").write_text("data")
    (final / "current").symlink_to("target")

    with pytest.raises(CandidateCaptureError, match="symlink while disabled"):
        capture(baseline, final, CandidateStore(tmp_path / "disabled-store"))

    store = CandidateStore(tmp_path / "enabled-store")
    candidate = capture(
        baseline,
        final,
        store,
        spec=overlay_spec(allow_internal_symlinks=True),
    )
    link = next(
        change
        for change in store.load_candidate(candidate.digest).payload["changes"]
        if change["kind"] == "symlink"
    )
    assert link == {
        "root": "/app",
        "path": "current",
        "kind": "symlink",
        "target": "target",
    }


def test_overlay_type_replacement_deletes_every_old_descendant(tmp_path: Path):
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    (baseline / "cache" / "nested").mkdir(parents=True)
    (baseline / "cache" / "nested" / "value").write_text("old")
    final.mkdir()
    (final / "cache").write_text("replacement")
    store = CandidateStore(tmp_path / "store")

    candidate = capture(baseline, final, store)
    changes = store.load_candidate(candidate.digest).payload["changes"]

    assert [(change["path"], change["kind"]) for change in changes] == [
        ("cache", "regular_file"),
        ("cache/nested", "absent"),
        ("cache/nested/value", "absent"),
    ]


def test_interrupted_overlay_transaction_leaves_no_orphaned_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    baseline, final = root_pair(tmp_path)
    (final / "changed.txt").write_bytes(b"new content")
    store = CandidateStore(tmp_path / "store")
    original = CandidateStoreTransaction.put_blob

    def interrupt(transaction: CandidateStoreTransaction, content: bytes) -> str:
        original(transaction, content)
        raise KeyboardInterrupt

    monkeypatch.setattr(CandidateStoreTransaction, "put_blob", interrupt)
    with pytest.raises(KeyboardInterrupt):
        capture(baseline, final, store)

    assert not any(path.is_file() for path in store.blobs_root.rglob("*"))
    assert not any(path.is_file() for path in store.candidates_root.rglob("*"))
    assert not any(store.transactions_root.iterdir())


def test_store_recovers_blob_promoted_before_interrupted_commit(tmp_path: Path):
    store = CandidateStore(tmp_path / "store")
    transaction = store.transaction()
    blob_digest = transaction.put_blob(b"staged")
    staged = transaction.staged_blobs / blob_digest.removeprefix("sha256:")
    promoted = store._blob_path(blob_digest)
    promoted.parent.mkdir(parents=True)
    os.replace(staged, promoted)
    candidate_digest = "sha256:" + hashlib.sha256(b"never-published").hexdigest()
    journal = {
        "candidate_digest": candidate_digest,
        "new_blobs": [blob_digest],
    }
    (transaction.path / "journal.json").write_text(
        json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n"
    )

    recovered = CandidateStore(store.root)

    assert not promoted.exists()
    assert not any(recovered.transactions_root.iterdir())


def test_overlay_load_rejects_malformed_stored_manifest(tmp_path: Path):
    baseline, final = root_pair(tmp_path)
    (final / "changed.txt").write_text("after\n")
    store = CandidateStore(tmp_path / "store")
    valid = capture(baseline, final, store)
    payload = copy.deepcopy(store.load_candidate(valid.digest).payload)
    payload["changes"][0]["unexpected"] = True
    malformed = store.put_candidate("filesystem_overlay", BASELINE, payload)

    with pytest.raises(CandidateStoreError, match="invalid shape"):
        store.load_candidate(malformed.digest)


def test_overlay_load_rejects_escaping_stored_path(tmp_path: Path):
    baseline, final = root_pair(tmp_path)
    (final / "changed.txt").write_text("after\n")
    store = CandidateStore(tmp_path / "store")
    valid = capture(baseline, final, store)
    payload = copy.deepcopy(store.load_candidate(valid.digest).payload)
    payload["changes"][0]["path"] = "../escape"
    malformed = store.put_candidate("filesystem_overlay", BASELINE, payload)

    with pytest.raises(CandidateStoreError, match="change path is invalid"):
        store.load_candidate(malformed.digest)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Config", "config"),
        ("caf\N{LATIN SMALL LETTER E WITH ACUTE}", "cafe\N{COMBINING ACUTE ACCENT}"),
    ],
)
def test_overlay_load_rejects_stored_portable_path_aliases(
    tmp_path: Path, first: str, second: str
):
    baseline, final = root_pair(tmp_path)
    (final / "changed.txt").write_text("after\n")
    store = CandidateStore(tmp_path / "store")
    valid = capture(baseline, final, store)
    payload = copy.deepcopy(store.load_candidate(valid.digest).payload)
    original = payload["changes"][0]
    aliases = [
        {**original, "path": first},
        {**original, "path": second},
    ]
    payload["changes"] = sorted(aliases, key=lambda item: item["path"].encode("utf-8"))
    payload["changed_paths"] = 2
    payload["changed_bytes"] = 2 * original["size"]
    malformed = store.put_candidate("filesystem_overlay", BASELINE, payload)

    with pytest.raises(CandidateStoreError, match="changes contain path aliases"):
        store.load_candidate(malformed.digest)


def test_overlay_replay_reconstructs_exact_final_state(tmp_path: Path):
    baseline, final = root_pair(tmp_path)
    (baseline / "current").symlink_to("unchanged.txt")
    shutil.rmtree(final / "removed")
    (final / "changed.txt").write_text("after\n")
    (final / "new-dir").mkdir()
    executable = final / "new-dir" / "tool"
    executable.write_text("run\n")
    executable.chmod(0o700)
    (final / "current").symlink_to("changed.txt")
    spec = overlay_spec(allow_internal_symlinks=True)
    store = CandidateStore(tmp_path / "store")
    candidate = capture(baseline, final, store, spec=spec)
    replay = tmp_path / "replay"
    shutil.copytree(baseline, replay, symlinks=True)
    limits = local_limits()
    baseline_scan = scan_overlay_roots(
        ("/app",), {"/app": replay}, limits=limits, label="baseline"
    )

    replay_filesystem_overlay(
        candidate,
        store,
        {"/app": replay},
        spec=spec,
        expected_baseline_digest=BASELINE,
        baseline=baseline_scan,
        scan_limits=limits,
    )

    expected = scan_overlay_root("/app", final, limits=limits)
    actual = scan_overlay_root("/app", replay, limits=limits)
    assert actual.digest == expected.digest
    assert (replay / "current").readlink() == Path("changed.txt")
    assert stat.S_IMODE((replay / "new-dir" / "tool").stat().st_mode) == 0o755


def test_overlay_replay_rejects_forged_baseline_digest(tmp_path: Path):
    baseline, final = root_pair(tmp_path)
    (final / "changed.txt").write_text("after\n")
    store = CandidateStore(tmp_path / "store")
    valid = capture(baseline, final, store)
    payload = copy.deepcopy(store.load_candidate(valid.digest).payload)
    payload["roots"][0]["baseline_tree_digest"] = "sha256:" + "f" * 64
    forged = store.put_candidate("filesystem_overlay", BASELINE, payload)
    replay = tmp_path / "replay"
    shutil.copytree(baseline, replay)

    with pytest.raises(CandidateReplayError, match="baseline root mismatch"):
        replay_filesystem_overlay(
            forged,
            store,
            {"/app": replay},
            spec=overlay_spec(),
            expected_baseline_digest=BASELINE,
            scan_limits=local_limits(),
        )


def test_overlay_replay_rejects_forged_final_state_digest(tmp_path: Path):
    baseline, final = root_pair(tmp_path)
    (final / "changed.txt").write_text("after\n")
    store = CandidateStore(tmp_path / "store")
    valid = capture(baseline, final, store)
    payload = copy.deepcopy(store.load_candidate(valid.digest).payload)
    payload["roots"][0]["final_tree_digest"] = "sha256:" + "f" * 64
    forged = store.put_candidate("filesystem_overlay", BASELINE, payload)
    replay = tmp_path / "replay"
    shutil.copytree(baseline, replay)

    with pytest.raises(CandidateReplayError, match="final root mismatch"):
        replay_filesystem_overlay(
            forged,
            store,
            {"/app": replay},
            spec=overlay_spec(),
            expected_baseline_digest=BASELINE,
            scan_limits=local_limits(),
        )


def test_overlay_replay_never_follows_parent_symlink(tmp_path: Path):
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    (baseline / "nested").mkdir(parents=True)
    (baseline / "nested" / "value").write_text("old")
    shutil.copytree(baseline, final)
    (final / "nested" / "value").write_text("new")
    store = CandidateStore(tmp_path / "store")
    candidate = capture(baseline, final, store)
    replay = tmp_path / "replay"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "value").write_text("outside")
    shutil.copytree(baseline, replay)
    limits = local_limits()
    baseline_scan = scan_overlay_roots(
        ("/app",), {"/app": replay}, limits=limits, label="baseline"
    )
    shutil.rmtree(replay / "nested")
    (replay / "nested").symlink_to(outside)

    with pytest.raises(CandidateReplayError, match="parent is not a real directory"):
        replay_filesystem_overlay(
            candidate,
            store,
            {"/app": replay},
            spec=overlay_spec(),
            expected_baseline_digest=BASELINE,
            baseline=baseline_scan,
            scan_limits=limits,
        )
    assert (outside / "value").read_text() == "outside"


def test_overlay_replay_rechecks_row_bounds_and_symlink_opt_in(tmp_path: Path):
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    baseline.mkdir()
    final.mkdir()
    (final / "target").write_text("content")
    (final / "current").symlink_to("target")
    store = CandidateStore(tmp_path / "store")
    candidate = capture(
        baseline,
        final,
        store,
        spec=overlay_spec(allow_internal_symlinks=True),
    )

    with pytest.raises(CandidateReplayError, match="row bounds"):
        replay_filesystem_overlay(
            candidate,
            store,
            {"/app": baseline},
            spec=overlay_spec(max_changed_paths=1, allow_internal_symlinks=True),
            expected_baseline_digest=BASELINE,
            scan_limits=local_limits(),
        )
    with pytest.raises(CandidateReplayError, match="disabled symlinks"):
        replay_filesystem_overlay(
            candidate,
            store,
            {"/app": baseline},
            spec=overlay_spec(allow_internal_symlinks=False),
            expected_baseline_digest=BASELINE,
            scan_limits=local_limits(),
        )
