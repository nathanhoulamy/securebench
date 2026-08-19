"""Internal evidence and public split-verification result models."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from securebench.verification.json_data import canonical_json_bytes, json_digest


VerificationStatus = Literal["passed", "failed", "infrastructure_error"]
CheckStatus = Literal["passed", "failed", "infrastructure_error"]
RESULT_SCHEMA_VERSION = "3"


@dataclass(frozen=True)
class OracleCase:
    """One host-generated challenge and its host-only scoring context."""

    challenge: Any
    context: Any

    def __post_init__(self) -> None:
        _json_bytes(self.challenge, "Oracle challenge")
        _json_bytes(self.context, "Oracle case context")


@dataclass(frozen=True)
class ProtocolCaseEvidence:
    """Host-internal observation from one fresh Evaluation sandbox."""

    check_id: str
    case_index: int
    challenge_digest: str
    status: Literal["observed", "candidate_error"]
    exit_status: int | None = None
    timed_out: bool = False
    duration_ms: int = 0
    observation: Any = None
    observation_bytes: int = 0
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.check_id:
            raise ValueError("protocol evidence check_id must be non-empty")
        if isinstance(self.case_index, bool) or not isinstance(self.case_index, int) or self.case_index < 0:
            raise ValueError("protocol evidence case_index must be a non-negative integer")
        if not _is_sha256_digest(self.challenge_digest):
            raise ValueError("protocol evidence challenge_digest must be a sha256 digest")
        if self.status not in {"observed", "candidate_error"}:
            raise ValueError("protocol evidence status is invalid")
        if self.exit_status is not None and (
            isinstance(self.exit_status, bool) or not isinstance(self.exit_status, int)
        ):
            raise ValueError("protocol evidence exit_status must be an integer or null")
        if not isinstance(self.timed_out, bool):
            raise ValueError("protocol evidence timed_out must be a boolean")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or self.duration_ms < 0:
            raise ValueError("protocol evidence duration_ms must be a non-negative integer")
        if (
            isinstance(self.observation_bytes, bool)
            or not isinstance(self.observation_bytes, int)
            or self.observation_bytes < 0
        ):
            raise ValueError("protocol evidence observation_bytes must be a non-negative integer")
        if self.status == "observed":
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("observed protocol evidence may not contain an error")
            _json_bytes(self.observation, "protocol observation")
        else:
            if not self.error_code or not self.error_message:
                raise ValueError("candidate-error protocol evidence requires an error")
            if self.observation is not None:
                raise ValueError("candidate-error protocol evidence may not contain an observation")

    def internal_record(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "case_index": self.case_index,
            "challenge_digest": self.challenge_digest,
            "status": self.status,
            "process": {
                "exit_status": self.exit_status,
                "timed_out": self.timed_out,
                "duration_ms": self.duration_ms,
            },
            "observation": self.observation,
            "observation_bytes": self.observation_bytes,
            "error": (
                None
                if self.error_code is None
                else {"code": self.error_code, "message": self.error_message}
            ),
        }

    @property
    def digest(self) -> str:
        return json_digest(self.internal_record())


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
        return json_digest(self.internal_record())


@dataclass(frozen=True)
class OracleVerdict:
    """Only authoritative correctness output of verification."""

    passed: bool
    score: float
    check_outcomes: dict[str, bool]
    public_diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise ValueError("Oracle passed must be a boolean")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise ValueError("Oracle score must be numeric")
        if not math.isfinite(float(self.score)) or not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("Oracle score must be between 0 and 1")
        if not isinstance(self.public_diagnostics, dict):
            raise ValueError("Oracle public_diagnostics must be an object")
        _json_bytes(self.public_diagnostics, "Oracle public_diagnostics")
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

    def __post_init__(self) -> None:
        if not self.id or not self.type:
            raise ValueError("check result id and type must be non-empty")
        if self.status not in {"passed", "failed", "infrastructure_error"}:
            raise ValueError("check result status is invalid")
        if isinstance(self.cases, bool) or not isinstance(self.cases, int) or self.cases < 0:
            raise ValueError("check result cases must be a non-negative integer")
        if not all(_is_sha256_digest(value) for value in self.evidence_digests):
            raise ValueError("check result evidence_digests must contain sha256 digests")


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
    baseline_digest: str
    verification_digest: str
    checks: tuple[CheckResultSummary, ...] = ()
    public_diagnostics: dict[str, Any] = field(default_factory=dict)
    infrastructure_error: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.status == "passed" and not self.passed:
            raise ValueError("passed verification status requires passed=true")
        if self.status != "passed" and self.passed:
            raise ValueError("non-passed verification status requires passed=false")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise ValueError("verification score must be numeric")
        if not math.isfinite(float(self.score)) or not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("verification score must be between 0 and 1")
        if self.status == "infrastructure_error" and self.infrastructure_error is None:
            raise ValueError("infrastructure_error status requires infrastructure_error details")
        if self.status != "infrastructure_error" and self.infrastructure_error is not None:
            raise ValueError("infrastructure_error details require infrastructure_error status")
        for field_name in (
            "manifest_digest",
            "row_digest",
            "image_digest",
            "baseline_digest",
            "verification_digest",
        ):
            if not _is_sha256_digest(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a sha256 digest")
        if (self.candidate_type is None) != (self.candidate_digest is None):
            raise ValueError("candidate type and digest must both be set or both be null")
        if self.candidate_type is not None and self.candidate_type not in {
            "file_bundle",
            "git_patch",
            "filesystem_overlay",
        }:
            raise ValueError("candidate type is invalid")
        if self.candidate_digest is not None and not _is_sha256_digest(self.candidate_digest):
            raise ValueError("candidate digest must be a sha256 digest")
        if len({check.id for check in self.checks}) != len(self.checks):
            raise ValueError("check result ids must be unique")
        if not isinstance(self.public_diagnostics, dict):
            raise ValueError("public_diagnostics must be an object")
        diagnostics = _json_bytes(self.public_diagnostics, "public_diagnostics")
        if len(diagnostics) > 64 * 1024:
            raise ValueError("public_diagnostics exceeded its bound")
        if self.infrastructure_error is not None:
            if set(self.infrastructure_error) != {"code", "message"} or not all(
                isinstance(value, str) and value
                for value in self.infrastructure_error.values()
            ):
                raise ValueError("infrastructure_error must contain non-empty code and message")

    def to_record(self, *, run_id: str, execution_digest: str) -> dict[str, Any]:
        if not _is_sha256_digest(execution_digest):
            raise ValueError("execution_digest must be a sha256 digest")
        record: dict[str, Any] = {
            "schema_version": RESULT_SCHEMA_VERSION,
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
                "baseline_digest": self.baseline_digest,
                "verification_digest": self.verification_digest,
                "execution_digest": execution_digest,
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


def _is_sha256_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    hexadecimal = value.removeprefix("sha256:")
    return len(hexadecimal) == 64 and all(character in "0123456789abcdef" for character in hexadecimal)


def _json_bytes(value: Any, field_name: str) -> bytes:
    try:
        return canonical_json_bytes(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite JSON data") from exc
