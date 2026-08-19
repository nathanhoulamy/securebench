"""Passive artifact-check execution without candidate code execution."""

from __future__ import annotations

from typing import Any

from securebench.candidates.models import StoredCandidate
from securebench.candidates.store import CandidateStore
from securebench.schemas.benchmark import ArtifactCheck, ArtifactSpec, FileBundleCandidate
from securebench.tasks import CompiledTaskV2
from securebench.verification.models import (
    ArtifactEvidence,
    CandidateObservationError,
    CheckResultSummary,
    OracleVerdict,
    ParserRejected,
    VerificationInfrastructureError,
    VerificationResultV2,
)
from securebench.verification.oracle import OracleProcessSession, OracleSession
from securebench.verification.parsers import ParserRegistry, default_parser_registry


class ArtifactVerificationEngine:
    """Execute artifact-only checks and route all correctness to the Oracle."""

    def __init__(self, parsers: ParserRegistry | None = None) -> None:
        self.parsers = parsers or default_parser_registry()

    def verify(
        self,
        task: CompiledTaskV2,
        candidate: StoredCandidate,
        store: CandidateStore,
        *,
        run_seed: str,
        oracle: OracleSession | None = None,
    ) -> VerificationResultV2:
        session = oracle
        owns_session = session is None
        try:
            if session is None:
                session = OracleProcessSession(_oracle_root(task))
            session.initialize(task, run_seed=run_seed)
            summaries: list[CheckResultSummary] = []
            for check in task.verification.checks:
                if not isinstance(check, ArtifactCheck):
                    raise VerificationInfrastructureError(
                        "protocol_engine_unavailable",
                        "This implementation batch does not yet execute protocol checks",
                    )
                evidence = tuple(
                    self._observe(task, candidate, store, check, artifact)
                    for artifact in check.artifacts
                )
                for item in evidence:
                    session.evaluate_artifact(item)
                summaries.append(
                    CheckResultSummary(
                        id=check.id,
                        type="artifact",
                        status="passed",
                        evidence_digests=tuple(item.digest for item in evidence),
                    )
                )
            verdict = session.finalize()
            summaries = _apply_oracle_outcomes(summaries, verdict)
            return _result(task, candidate, verdict, tuple(summaries))
        except VerificationInfrastructureError as exc:
            return _infrastructure_result(task, candidate, exc)
        except Exception as exc:
            return _infrastructure_result(
                task,
                candidate,
                VerificationInfrastructureError(
                    "verification_internal_error",
                    f"Trusted verification failed: {type(exc).__name__}",
                ),
            )
        finally:
            if owns_session and session is not None:
                session.close()

    def _observe(
        self,
        task: CompiledTaskV2,
        candidate: StoredCandidate,
        store: CandidateStore,
        check: ArtifactCheck,
        artifact: ArtifactSpec,
    ) -> ArtifactEvidence:
        try:
            kind, digest, size, value = _candidate_artifact(candidate, store, artifact)
            profile = self.parsers.profile(artifact.parser)
            if kind == "regular_file":
                if profile.input_kind != "bytes":
                    raise VerificationInfrastructureError(
                        "parser_contract_mismatch", "Registered parser input kind does not match artifact"
                    )
                assert isinstance(value, bytes)
                parsed = self.parsers.parse_bytes(artifact.parser, value)
            else:
                if profile.input_kind != "tree":
                    raise VerificationInfrastructureError(
                        "parser_contract_mismatch", "Registered parser input kind does not match artifact"
                    )
                assert isinstance(value, dict)
                parsed = self.parsers.parse_tree(artifact.parser, value)
            return ArtifactEvidence(
                check_id=check.id,
                artifact_id=artifact.id,
                status="observed",
                source_kind=kind,
                source_digest=digest,
                source_size=size,
                parser=artifact.parser,
                parsed_value=parsed,
            )
        except (CandidateObservationError, ParserRejected) as exc:
            return ArtifactEvidence(
                check_id=check.id,
                artifact_id=artifact.id,
                status="candidate_error",
                source_kind="unknown",
                parser=artifact.parser,
                error_code=exc.code,
                error_message=exc.public_message,
            )


def _candidate_artifact(
    candidate: StoredCandidate,
    store: CandidateStore,
    artifact: ArtifactSpec,
) -> tuple[str, str | None, int, bytes | dict[str, Any]]:
    manifest = store.load_candidate(candidate.digest)
    if manifest.type != "file_bundle":
        raise VerificationInfrastructureError(
            "artifact_materializer_unavailable",
            "Path artifacts for patches and overlays are not implemented in this batch",
        )
    source_entry = artifact.source.entry
    if source_entry is None:
        raise VerificationInfrastructureError(
            "artifact_source_invalid", "File-bundle artifact source must reference an entry"
        )
    entries = manifest.payload.get("entries")
    if not isinstance(entries, list):
        raise VerificationInfrastructureError(
            "candidate_manifest_invalid", "Stored candidate entry manifest is invalid"
        )
    entry = next(
        (
            value
            for value in entries
            if isinstance(value, dict) and value.get("id") == source_entry
        ),
        None,
    )
    if entry is None:
        raise CandidateObservationError(
            "artifact_missing", f"Candidate artifact entry {source_entry!r} is missing"
        )
    kind = entry.get("kind")
    if kind == "regular_file":
        blob = entry.get("blob")
        size = entry.get("size")
        maximum = artifact.limits.max_bytes
        if not isinstance(blob, str) or not isinstance(size, int) or maximum is None:
            raise VerificationInfrastructureError(
                "candidate_manifest_invalid", "Stored regular-file entry is invalid"
            )
        if size > maximum:
            raise CandidateObservationError(
                "artifact_too_large", f"Candidate artifact {artifact.id!r} exceeds its parser bound"
            )
        return "regular_file", blob, size, store.read_blob(blob, expected_size=size)
    if kind == "directory_tree":
        nodes = entry.get("nodes")
        maximum_files = artifact.limits.max_files
        maximum_bytes = artifact.limits.max_total_bytes
        if not isinstance(nodes, list) or maximum_files is None or maximum_bytes is None:
            raise VerificationInfrastructureError(
                "candidate_manifest_invalid", "Stored directory-tree entry is invalid"
            )
        total_bytes = sum(
            value.get("size", len(str(value.get("target", "")).encode("utf-8")))
            for value in nodes
            if isinstance(value, dict)
        )
        if len(nodes) > maximum_files or total_bytes > maximum_bytes:
            raise CandidateObservationError(
                "artifact_too_large", f"Candidate artifact {artifact.id!r} exceeds its tree bounds"
            )
        return "directory_tree", candidate.digest, total_bytes, {"nodes": nodes}
    raise VerificationInfrastructureError(
        "candidate_manifest_invalid", "Stored candidate entry kind is invalid"
    )


def _oracle_root(task: CompiledTaskV2) -> str:
    _, identifier = task.verification.oracle.split(".", 1)
    resource = task.resources.resources.get(f"host.{identifier}")
    if resource is None or not isinstance(resource.value, dict):
        raise VerificationInfrastructureError(
            "oracle_resource_missing", "Oracle host resource is unavailable"
        )
    source_path = resource.value.get("source_path")
    if not isinstance(source_path, str):
        raise VerificationInfrastructureError(
            "oracle_resource_invalid", "Oracle host resource is invalid"
        )
    return source_path


def _apply_oracle_outcomes(
    summaries: list[CheckResultSummary],
    verdict: OracleVerdict,
) -> list[CheckResultSummary]:
    output = []
    for summary in summaries:
        passed = verdict.check_outcomes.get(summary.id, verdict.passed)
        output.append(
            CheckResultSummary(
                id=summary.id,
                type=summary.type,
                status="passed" if passed else "failed",
                evidence_digests=summary.evidence_digests,
                cases=summary.cases,
            )
        )
    return output


def _result(
    task: CompiledTaskV2,
    candidate: StoredCandidate,
    verdict: OracleVerdict,
    summaries: tuple[CheckResultSummary, ...],
) -> VerificationResultV2:
    return VerificationResultV2(
        task_id=task.id,
        benchmark_id=task.benchmark_id,
        status="passed" if verdict.passed else "failed",
        passed=verdict.passed,
        score=float(verdict.score),
        candidate_type=candidate.type,
        candidate_digest=candidate.digest,
        execution_profile=task.verification.execution_profile,
        manifest_digest=task.manifest_digest,
        row_digest=task.row_digest,
        image_digest=task.environment.image,
        checks=summaries,
        public_diagnostics=_bounded_public_diagnostics(verdict.public_diagnostics),
    )


def _infrastructure_result(
    task: CompiledTaskV2,
    candidate: StoredCandidate,
    error: VerificationInfrastructureError,
) -> VerificationResultV2:
    return VerificationResultV2(
        task_id=task.id,
        benchmark_id=task.benchmark_id,
        status="infrastructure_error",
        passed=False,
        score=0.0,
        candidate_type=candidate.type,
        candidate_digest=candidate.digest,
        execution_profile=task.verification.execution_profile,
        manifest_digest=task.manifest_digest,
        row_digest=task.row_digest,
        image_digest=task.environment.image,
        infrastructure_error={"code": error.code, "message": error.public_message},
    )


def _bounded_public_diagnostics(value: dict[str, Any]) -> dict[str, Any]:
    import json

    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VerificationInfrastructureError(
            "oracle_diagnostics_invalid", "Oracle public diagnostics are not JSON serializable"
        ) from exc
    if len(encoded) > 64 * 1024:
        raise VerificationInfrastructureError(
            "oracle_diagnostics_too_large", "Oracle public diagnostics exceeded their bound"
        )
    return value
