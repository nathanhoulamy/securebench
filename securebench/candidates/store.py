"""Content-addressed storage for replayable candidates."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from securebench.candidates.models import (
    CANDIDATE_MANIFEST_VERSION,
    CandidateManifest,
    CandidateStoreError,
    CandidateType,
    StoredCandidate,
)


class CandidateStore:
    """Store candidate manifests and payload blobs by SHA-256 digest."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.blobs_root = self.root / "blobs" / "sha256"
        self.candidates_root = self.root / "candidates" / "sha256"
        self.blobs_root.mkdir(parents=True, exist_ok=True)
        self.candidates_root.mkdir(parents=True, exist_ok=True)

    def put_blob(self, content: bytes) -> str:
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
            content = target.read_bytes()
        except OSError as exc:
            raise CandidateStoreError(f"candidate blob is missing: {digest}") from exc
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
        encoded = _canonical_json(document)
        digest = _digest_bytes(encoded)
        target = self._candidate_path(digest) / "manifest.json"
        if target.exists():
            existing = target.read_bytes()
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
            encoded = path.read_bytes()
        except OSError as exc:
            raise CandidateStoreError(f"candidate manifest is missing: {digest}") from exc
        if _digest_bytes(encoded) != digest:
            raise CandidateStoreError(f"candidate manifest digest mismatch: {digest}")
        try:
            document = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise CandidateStoreError(f"candidate manifest is invalid JSON: {digest}") from exc
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


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


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
