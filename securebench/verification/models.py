"""Internal evidence and public split-verification result models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal


VerificationStatus = Literal["passed", "failed", "infrastructure_error"]
CheckStatus = Literal["passed", "failed", "infrastructure_error"]


@dataclass(frozen=True)
class ArtifactEvidence:
    """Host-internal artifact observation passed to the Oracle."""

    check_id: str
    artifact_id: str
    status: Literal["observed", "candidate_error"]
    source_kind: str
    source_digest: str | None = None
    source_size: int | None = None
    parser: str | None = None
    parsed_value: Any = None
    error_code: str | None = None
    error_message: str | None = None

    def internal_record(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "artifact_id": self.artifact_id,
            "status": self.status,
            "source": {
                "kind": self.source_kind,
                "digest": self.source_digest,
                "size": self.source_size,
            },
            "parser": self.parser,
            "parsed_value": self.parsed_value,
            "error": (
                None
                if self.error_code is None
                else {"code": self.error_code, "message": self.error_message}
            ),
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.internal_record(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class OracleVerdict:
    """Only authoritative correctness output of verification."""

    passed: bool
    score: float
    public_diagnostics: dict[str, Any] = field(default_factory=dict)
    check_outcomes: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise ValueError("Oracle passed must be a boolean")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise ValueError("Oracle score must be numeric")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("Oracle score must be between 0 and 1")
        if not isinstance(self.public_diagnostics, dict):
            raise ValueError("Oracle public_diagnostics must be an object")
        if not isinstance(self.check_outcomes, dict) or not all(
            isinstance(key, str) and isinstance(value, bool)
            for key, value in self.check_outcomes.items()
        ):
            raise ValueError("Oracle check_outcomes must map check ids to booleans")


@dataclass(frozen=True)
class CheckResultSummary:
    id: str
    type: str
    status: CheckStatus
    evidence_digests: tuple[str, ...] = ()
    cases: int = 0


@dataclass(frozen=True)
class VerificationResultV2:
    """Sanitized result safe for persistent benchmark output."""

    task_id: str
    benchmark_id: str
    status: VerificationStatus
    passed: bool
    score: float
    candidate_type: str | None
    candidate_digest: str | None
    execution_profile: str
    manifest_digest: str
    row_digest: str
    image_digest: str
    checks: tuple[CheckResultSummary, ...] = ()
    public_diagnostics: dict[str, Any] = field(default_factory=dict)
    infrastructure_error: dict[str, str] | None = None

    def to_record(self, *, run_id: str) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema_version": "1",
            "run_id": run_id,
            "task_id": self.task_id,
            "benchmark_id": self.benchmark_id,
            "status": self.status,
            "passed": self.passed,
            "score": float(self.score),
            "candidate": {
                "type": self.candidate_type,
                "digest": self.candidate_digest,
            },
            "execution_profile": self.execution_profile,
            "provenance": {
                "manifest_digest": self.manifest_digest,
                "row_digest": self.row_digest,
                "image_digest": self.image_digest,
            },
            "checks": [
                {
                    "id": check.id,
                    "type": check.type,
                    "status": check.status,
                    "cases": check.cases,
                    "evidence_digests": list(check.evidence_digests),
                }
                for check in self.checks
            ],
            "public_diagnostics": self.public_diagnostics,
        }
        if self.infrastructure_error is not None:
            record["infrastructure_error"] = self.infrastructure_error
        return record


class VerificationInfrastructureError(RuntimeError):
    """Trusted verification machinery failed independently of the candidate."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.public_message = message
        super().__init__(message)


class CandidateObservationError(ValueError):
    """Candidate data was missing, malformed, or outside declared bounds."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.public_message = message
        super().__init__(message)


class ParserRejected(ValueError):
    """A registered parser safely rejected hostile candidate data."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.public_message = message
        super().__init__(message)
