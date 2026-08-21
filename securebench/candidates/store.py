"""Content-addressed storage for replayable candidates."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from securebench.candidates.models import (
    CANDIDATE_MANIFEST_VERSION,
    CandidateManifest,
    CandidateStoreError,
    CandidateType,
    StoredCandidate,
)
from securebench.data_formats import strict_json_loads


MAX_CANDIDATE_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_CANDIDATE_BLOB_BYTES = 256 * 1024 * 1024


class CandidateStoreCapacityError(CandidateStoreError):
    """A candidate exceeds a fixed durable-store backend capacity."""


class CandidateStore:
    """Store candidate manifests and payload blobs by SHA-256 digest."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.blobs_root = self.root / "blobs" / "sha256"
        self.candidates_root = self.root / "candidates" / "sha256"
        self.transactions_root = self.root / "transactions"
        self._transaction_lock = threading.RLock()
        self.blobs_root.mkdir(parents=True, exist_ok=True)
        self.candidates_root.mkdir(parents=True, exist_ok=True)
        self.transactions_root.mkdir(parents=True, exist_ok=True)
        self._recover_transactions()

    def transaction(self) -> "CandidateStoreTransaction":
        """Create an isolated staging transaction for one durable candidate."""
        return CandidateStoreTransaction(self)

    def put_blob(self, content: bytes) -> str:
        if len(content) > MAX_CANDIDATE_BLOB_BYTES:
            raise CandidateStoreCapacityError("candidate blob exceeds the store capacity")
        digest = _digest_bytes(content)
        target = self._blob_path(digest)
        if target.exists():
            self.read_blob(digest)
            return digest
        _atomic_write(target, content)
        return digest

    def read_blob(self, digest: str, *, expected_size: int | None = None) -> bytes:
        target = self._blob_path(digest)
        try:
            maximum = MAX_CANDIDATE_BLOB_BYTES if expected_size is None else expected_size
            if (
                isinstance(maximum, bool)
                or not isinstance(maximum, int)
                or maximum < 0
                or maximum > MAX_CANDIDATE_BLOB_BYTES
            ):
                raise CandidateStoreCapacityError(
                    "candidate blob expected size is outside the store capacity"
                )
            content = _read_bounded_file(target, maximum)
        except OSError as exc:
            raise CandidateStoreError(f"candidate blob is missing: {digest}") from exc
        except CandidateStoreError:
            raise
        if len(content) > maximum:
            raise CandidateStoreError(f"candidate blob exceeds its expected size: {digest}")
        if _digest_bytes(content) != digest:
            raise CandidateStoreError(f"candidate blob digest mismatch: {digest}")
        if expected_size is not None and len(content) != expected_size:
            raise CandidateStoreError(
                f"candidate blob size mismatch for {digest}: expected {expected_size}, got {len(content)}"
            )
        return content

    def put_candidate(
        self,
        candidate_type: CandidateType,
        baseline_digest: str,
        payload: dict[str, Any],
    ) -> StoredCandidate:
        _, encoded, digest = _candidate_document(candidate_type, baseline_digest, payload)
        target = self._candidate_path(digest) / "manifest.json"
        if target.exists():
            existing = _read_bounded_file(target, MAX_CANDIDATE_MANIFEST_BYTES)
            if len(existing) > MAX_CANDIDATE_MANIFEST_BYTES:
                raise CandidateStoreCapacityError(
                    "candidate manifest exceeds the store capacity"
                )
            if existing != encoded or _digest_bytes(existing) != digest:
                raise CandidateStoreError(f"candidate manifest collision: {digest}")
        else:
            _atomic_write(target, encoded)
        return StoredCandidate(
            type=candidate_type,
            digest=digest,
            manifest_path=target,
            baseline_digest=baseline_digest,
        )

    def load_candidate(self, digest: str) -> CandidateManifest:
        path = self._candidate_path(digest) / "manifest.json"
        try:
            encoded = _read_bounded_file(path, MAX_CANDIDATE_MANIFEST_BYTES)
        except OSError as exc:
            raise CandidateStoreError(f"candidate manifest is missing: {digest}") from exc
        if len(encoded) > MAX_CANDIDATE_MANIFEST_BYTES:
            raise CandidateStoreCapacityError(
                f"candidate manifest exceeds the store capacity: {digest}"
            )
        if _digest_bytes(encoded) != digest:
            raise CandidateStoreError(f"candidate manifest digest mismatch: {digest}")
        try:
            document = strict_json_loads(encoded)
        except (UnicodeError, ValueError) as exc:
            raise CandidateStoreError(f"candidate manifest is invalid finite JSON: {digest}") from exc
        if not isinstance(document, dict) or set(document) != {
            "schema_version",
            "type",
            "baseline_digest",
            "payload",
        }:
            raise CandidateStoreError("candidate manifest has an invalid shape")
        if document["schema_version"] != CANDIDATE_MANIFEST_VERSION:
            raise CandidateStoreError("unsupported candidate manifest schema_version")
        candidate_type = document["type"]
        if candidate_type not in {"git_patch", "file_bundle", "filesystem_overlay"}:
            raise CandidateStoreError(f"unsupported stored candidate type: {candidate_type!r}")
        baseline_digest = document["baseline_digest"]
        try:
            _sha256_hex(baseline_digest)
        except CandidateStoreError as exc:
            raise CandidateStoreError("candidate manifest baseline_digest is invalid") from exc
        payload = document["payload"]
        if not isinstance(payload, dict):
            raise CandidateStoreError("candidate manifest payload must be an object")
        if candidate_type == "filesystem_overlay":
            from securebench.candidates.overlay import validate_filesystem_overlay_payload

            validate_filesystem_overlay_payload(payload, store=self)
        return CandidateManifest(
            schema_version=CANDIDATE_MANIFEST_VERSION,
            type=candidate_type,
            baseline_digest=baseline_digest,
            payload=payload,
        )

    def reference(self, digest: str) -> StoredCandidate:
        manifest = self.load_candidate(digest)
        return StoredCandidate(
            type=manifest.type,
            digest=digest,
            manifest_path=self._candidate_path(digest) / "manifest.json",
            baseline_digest=manifest.baseline_digest,
        )

    def _blob_path(self, digest: str) -> Path:
        hexadecimal = _sha256_hex(digest)
        return self.blobs_root / hexadecimal[:2] / hexadecimal

    def _candidate_path(self, digest: str) -> Path:
        hexadecimal = _sha256_hex(digest)
        return self.candidates_root / hexadecimal[:2] / hexadecimal

    def _recover_transactions(self) -> None:
        with self._transaction_lock:
            for transaction_dir in tuple(self.transactions_root.iterdir()):
                if transaction_dir.is_symlink() or not transaction_dir.is_dir():
                    raise CandidateStoreError("candidate transaction path is unsafe")
                journal_path = transaction_dir / "journal.json"
                if journal_path.exists():
                    try:
                        journal = strict_json_loads(
                            _read_bounded_file(journal_path, MAX_CANDIDATE_MANIFEST_BYTES)
                        )
                    except (OSError, UnicodeError, ValueError) as exc:
                        raise CandidateStoreError(
                            "candidate transaction journal is invalid"
                        ) from exc
                    if (
                        not isinstance(journal, dict)
                        or set(journal) != {"candidate_digest", "new_blobs"}
                        or not isinstance(journal["new_blobs"], list)
                    ):
                        raise CandidateStoreError("candidate transaction journal has invalid shape")
                    candidate_digest = journal["candidate_digest"]
                    _sha256_hex(candidate_digest)
                    blob_digests = journal["new_blobs"]
                    for blob_digest in blob_digests:
                        if not isinstance(blob_digest, str):
                            raise CandidateStoreError(
                                "candidate transaction blob digest is invalid"
                            )
                        _sha256_hex(blob_digest)
                    if len(blob_digests) != len(set(blob_digests)):
                        raise CandidateStoreError(
                            "candidate transaction journal contains duplicate blobs"
                        )
                    candidate_exists = (
                        self._candidate_path(candidate_digest) / "manifest.json"
                    ).is_file()
                    if not candidate_exists:
                        for blob_digest in blob_digests:
                            self._blob_path(blob_digest).unlink(missing_ok=True)
                shutil.rmtree(transaction_dir)


class CandidateStoreTransaction:
    """Private blob staging with rollback and crash-recovery journaling."""

    def __init__(self, store: CandidateStore) -> None:
        self.store = store
        self.path = store.transactions_root / uuid.uuid4().hex
        self.staged_blobs = self.path / "blobs"
        self.path.mkdir(mode=0o700)
        self.staged_blobs.mkdir(mode=0o700)
        self._digests: set[str] = set()
        self._closed = False

    def put_blob(self, content: bytes) -> str:
        if self._closed:
            raise CandidateStoreError("candidate transaction is closed")
        if len(content) > MAX_CANDIDATE_BLOB_BYTES:
            raise CandidateStoreCapacityError("candidate blob exceeds the store capacity")
        digest = _digest_bytes(content)
        if digest in self._digests:
            return digest
        final = self.store._blob_path(digest)
        if final.exists():
            self.store.read_blob(digest, expected_size=len(content))
        else:
            _atomic_write(self.staged_blobs / _sha256_hex(digest), content)
        self._digests.add(digest)
        return digest

    def put_candidate(
        self,
        candidate_type: CandidateType,
        baseline_digest: str,
        payload: dict[str, Any],
    ) -> StoredCandidate:
        if self._closed:
            raise CandidateStoreError("candidate transaction is closed")
        document, encoded, digest = _candidate_document(
            candidate_type,
            baseline_digest,
            payload,
        )
        del document
        target = self.store._candidate_path(digest) / "manifest.json"
        promoted: list[Path] = []
        with self.store._transaction_lock:
            new_digests = sorted(
                value
                for value in self._digests
                if not self.store._blob_path(value).exists()
            )
            _atomic_write(
                self.path / "journal.json",
                _canonical_json(
                    {"candidate_digest": digest, "new_blobs": new_digests}
                ),
            )
            try:
                for blob_digest in sorted(self._digests):
                    final = self.store._blob_path(blob_digest)
                    if final.exists():
                        self.store.read_blob(blob_digest)
                        continue
                    staged = self.staged_blobs / _sha256_hex(blob_digest)
                    if not staged.is_file():
                        raise CandidateStoreError(
                            f"candidate transaction blob is missing: {blob_digest}"
                        )
                    final.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, final)
                    promoted.append(final)
                if target.exists():
                    existing = _read_bounded_file(target, MAX_CANDIDATE_MANIFEST_BYTES)
                    if existing != encoded or _digest_bytes(existing) != digest:
                        raise CandidateStoreError(f"candidate manifest collision: {digest}")
                else:
                    _atomic_write(target, encoded)
            except BaseException:
                published = False
                try:
                    if target.is_file():
                        existing = _read_bounded_file(
                            target, MAX_CANDIDATE_MANIFEST_BYTES
                        )
                        published = existing == encoded and _digest_bytes(existing) == digest
                except OSError:
                    published = False
                if not published:
                    for path in promoted:
                        path.unlink(missing_ok=True)
                raise
        self.close()
        return StoredCandidate(
            type=candidate_type,
            digest=digest,
            manifest_path=target,
            baseline_digest=baseline_digest,
        )

    def close(self) -> None:
        if self._closed:
            return
        shutil.rmtree(self.path, ignore_errors=False)
        self._closed = True

    def __enter__(self) -> "CandidateStoreTransaction":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._closed:
            self.close()


def _candidate_document(
    candidate_type: CandidateType,
    baseline_digest: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bytes, str]:
    if candidate_type not in {"git_patch", "file_bundle", "filesystem_overlay"}:
        raise CandidateStoreError(f"unsupported candidate type: {candidate_type!r}")
    try:
        _sha256_hex(baseline_digest)
    except CandidateStoreError as exc:
        raise CandidateStoreError("candidate baseline_digest must be a sha256 digest") from exc
    document = {
        "schema_version": CANDIDATE_MANIFEST_VERSION,
        "type": candidate_type,
        "baseline_digest": baseline_digest,
        "payload": payload,
    }
    try:
        encoded = _canonical_json(document)
    except (TypeError, ValueError) as exc:
        raise CandidateStoreError("candidate manifest payload is not canonical JSON") from exc
    if len(encoded) > MAX_CANDIDATE_MANIFEST_BYTES:
        raise CandidateStoreCapacityError("candidate manifest exceeds the store capacity")
    return document, encoded, _digest_bytes(encoded)


def _canonical_json(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except RecursionError as exc:
        raise ValueError("candidate manifest exceeds the nesting limit") from exc


def _digest_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _sha256_hex(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise CandidateStoreError(f"invalid sha256 digest: {value!r}")
    hexadecimal = value.removeprefix("sha256:")
    if len(hexadecimal) != 64 or any(character not in "0123456789abcdef" for character in hexadecimal):
        raise CandidateStoreError(f"invalid sha256 digest: {value!r}")
    return hexadecimal


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".candidate-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_bounded_file(path: Path, maximum_bytes: int) -> bytes:
    with path.open("rb") as stream:
        return stream.read(maximum_bytes + 1)
