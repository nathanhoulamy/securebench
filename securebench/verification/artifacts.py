"""Split-verification orchestration and passive artifact observation."""

from __future__ import annotations

import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from securebench.baselines import task_baseline_digest, task_verification_digest
from securebench.candidates.models import CandidateReplayError, StoredCandidate
from securebench.candidates.replay import replay_candidate
from securebench.candidates.store import CandidateStore
from securebench.errors import ConfigError
from securebench.schemas.benchmark import ArtifactCheck, ArtifactSpec, ProtocolCheck
from securebench.tasks import BenchmarkTask
from securebench.verification.json_data import canonical_json_bytes
from securebench.verification.models import (
    ArtifactEvidence,
    CandidateObservationError,
    CheckResultSummary,
    OracleVerdict,
    ParserRejected,
    VerificationInfrastructureError,
    VerificationResultV2,
)
from securebench.verification.oracle import (
    OracleProcessSession,
    OracleSession,
    oracle_resource_root,
)
from securebench.verification.passive_files import observe_bounded_path
from securebench.verification.parsers import ParserRegistry, default_parser_registry
from securebench.verification.protocol import ProtocolCheckRunner
from securebench.workspaces.cleanup import remove_untrusted_tree


class VerificationEngine:
    """Execute split checks while routing all correctness decisions to the Oracle."""

    def __init__(
        self,
        parsers: ParserRegistry | None = None,
        protocols: ProtocolCheckRunner | None = None,
    ) -> None:
        self.parsers = parsers or default_parser_registry()
        self.protocols = protocols or ProtocolCheckRunner(parsers=self.parsers)

    def verify(
        self,
        task: BenchmarkTask,
        candidate: StoredCandidate,
        store: CandidateStore,
        *,
        run_seed: str,
        oracle: OracleSession | None = None,
    ) -> VerificationResultV2:
        session = oracle
        owns_session = session is None
        result: VerificationResultV2 | None = None
        try:
            _validate_candidate_binding(task, candidate, store)
            if session is None:
                session = OracleProcessSession(oracle_resource_root(task))
            session.initialize(task, run_seed=run_seed)
            summaries: list[CheckResultSummary] = []
            for check in task.verification.checks:
                if isinstance(check, ProtocolCheck):
                    evidence = self.protocols.evaluate(task, candidate, store, check, session)
                    summaries.append(
                        CheckResultSummary(
                            id=check.id,
                            type="protocol",
                            status="passed",
                            evidence_digests=tuple(item.digest for item in evidence),
                            cases=len(evidence),
                        )
                    )
                    continue
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
            result = _result(task, candidate, verdict, tuple(summaries))
        except VerificationInfrastructureError as exc:
            result = _infrastructure_result(task, candidate, exc)
        except Exception as exc:
            result = _infrastructure_result(
                task,
                candidate,
                VerificationInfrastructureError(
                    "verification_internal_error",
                    f"Trusted verification failed: {type(exc).__name__}",
                ),
            )
        finally:
            if owns_session and session is not None:
                result = _result_after_oracle_close(task, candidate, session, result)
        if result is None:
            raise RuntimeError("verification ended without a result")
        return result

    def infrastructure_error(
        self,
        task: BenchmarkTask,
        *,
        code: str,
        message: str,
        candidate: StoredCandidate | None = None,
    ) -> VerificationResultV2:
        """Create a sanitized result when trusted row orchestration fails."""
        return _infrastructure_result(
            task,
            candidate,
            VerificationInfrastructureError(code, message),
        )

    def verify_candidate_error(
        self,
        task: BenchmarkTask,
        *,
        code: str,
        message: str,
        run_seed: str,
        oracle: OracleSession | None = None,
    ) -> VerificationResultV2:
        """Let the Oracle score a missing, timed-out, or uncapturable candidate."""
        session = oracle
        owns_session = session is None
        result: VerificationResultV2 | None = None
        try:
            _validate_task_inputs(task)
            if session is None:
                session = OracleProcessSession(oracle_resource_root(task))
            session.initialize(task, run_seed=run_seed)
            summaries: list[CheckResultSummary] = []
            for check in task.verification.checks:
                if isinstance(check, ProtocolCheck):
                    evidence = self.protocols.evaluate_candidate_error(
                        task,
                        check,
                        session,
                        code=code,
                        message=message,
                    )
                    summaries.append(
                        CheckResultSummary(
                            id=check.id,
                            type="protocol",
                            status="passed",
                            evidence_digests=tuple(item.digest for item in evidence),
                            cases=len(evidence),
                        )
                    )
                    continue
                evidence = tuple(
                    ArtifactEvidence(
                        check_id=check.id,
                        artifact_id=artifact.id,
                        status="candidate_error",
                        source_kind="unknown",
                        parser=artifact.parser,
                        error_code=code,
                        error_message=message,
                    )
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
            result = _result(task, None, verdict, tuple(summaries))
        except VerificationInfrastructureError as exc:
            result = _infrastructure_result(task, None, exc)
        except Exception as exc:
            result = _infrastructure_result(
                task,
                None,
                VerificationInfrastructureError(
                    "verification_internal_error",
                    f"Trusted verification failed: {type(exc).__name__}",
                ),
            )
        finally:
            if owns_session and session is not None:
                result = _result_after_oracle_close(task, None, session, result)
        if result is None:
            raise RuntimeError("verification ended without a result")
        return result

    def _observe(
        self,
        task: BenchmarkTask,
        candidate: StoredCandidate,
        store: CandidateStore,
        check: ArtifactCheck,
        artifact: ArtifactSpec,
    ) -> ArtifactEvidence:
        try:
            kind, digest, size, value = _candidate_artifact(
                task, candidate, store, artifact
            )
            profile = self.parsers.profile(artifact.parser)
            if kind == "regular_file":
                if profile.input_kind != "bytes":
                    raise VerificationInfrastructureError(
                        "parser_contract_mismatch",
                        "Registered parser input kind does not match artifact",
                    )
                assert isinstance(value, bytes)
                parsed = self.parsers.parse_bytes(artifact.parser, value)
            else:
                if profile.input_kind != "tree":
                    raise VerificationInfrastructureError(
                        "parser_contract_mismatch",
                        "Registered parser input kind does not match artifact",
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


def _result_after_oracle_close(
    task: BenchmarkTask,
    candidate: StoredCandidate | None,
    session: OracleSession,
    result: VerificationResultV2 | None,
) -> VerificationResultV2 | None:
    try:
        session.close()
    except VerificationInfrastructureError as exc:
        return _infrastructure_result(task, candidate, exc)
    except Exception:
        return _infrastructure_result(
            task,
            candidate,
            VerificationInfrastructureError(
                "oracle_cleanup_failed",
                "Oracle process cleanup failed",
            ),
        )
    return result


def _candidate_artifact(
    task: BenchmarkTask,
    candidate: StoredCandidate,
    store: CandidateStore,
    artifact: ArtifactSpec,
) -> tuple[str, str | None, int, bytes | dict[str, Any]]:
    manifest = store.load_candidate(candidate.digest)
    if manifest.type == "git_patch":
        return _git_patch_artifact(task, candidate, store, artifact)
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


def _git_patch_artifact(
    task: BenchmarkTask,
    candidate: StoredCandidate,
    store: CandidateStore,
    artifact: ArtifactSpec,
) -> tuple[str, str | None, int, bytes | dict[str, Any]]:
    source_path = artifact.source.path
    if source_path is None:
        raise VerificationInfrastructureError(
            "artifact_source_invalid", "git_patch artifact source must reference a path"
        )
    relative = PurePosixPath(source_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise VerificationInfrastructureError(
            "artifact_source_invalid", "Repository artifact path is invalid"
        )
    evaluation_root = Path(tempfile.mkdtemp(prefix="securebench-artifact-repository-"))
    try:
        # Import lazily: harness modules import execution-profile validation.
        from securebench.harnesses.shared import materialize_image_workdir

        try:
            materialize_image_workdir(task, evaluation_root)
            replay_candidate(task, candidate, store, evaluation_root)
        except (CandidateReplayError, ConfigError) as exc:
            raise VerificationInfrastructureError(
                "candidate_replay_failed", "Stored patch candidate could not be reconstructed"
            ) from exc
        observed = observe_bounded_path(
            evaluation_root,
            source_path,
            artifact.limits,
            subject=f"Candidate artifact {artifact.id!r}",
        )
        return observed.kind, observed.digest, observed.size, observed.value
    finally:
        try:
            remove_untrusted_tree(evaluation_root, image=task.environment.image)
        except Exception as exc:
            raise VerificationInfrastructureError(
                "artifact_cleanup_failed", "Passive artifact workspace cleanup failed"
            ) from exc


def _validate_candidate_binding(
    task: BenchmarkTask,
    candidate: StoredCandidate,
    store: CandidateStore,
) -> None:
    _validate_task_inputs(task)
    manifest = store.load_candidate(candidate.digest)
    if candidate.type != task.verification.candidate.type:
        raise VerificationInfrastructureError(
            "candidate_reference_mismatch",
            "Stored candidate type does not match the declared candidate shape",
        )
    if candidate.type != manifest.type:
        raise VerificationInfrastructureError(
            "candidate_reference_mismatch",
            "Stored candidate type does not match its reference",
        )
    if candidate.baseline_digest != manifest.baseline_digest:
        raise VerificationInfrastructureError(
            "candidate_reference_mismatch",
            "Stored candidate baseline does not match its reference",
        )
    if manifest.baseline_digest != task.baseline_digest:
        raise VerificationInfrastructureError(
            "candidate_baseline_mismatch",
            "Stored candidate was captured from a different baseline",
        )


def _validate_task_inputs(task: BenchmarkTask) -> None:
    if task_baseline_digest(task) != task.baseline_digest:
        raise VerificationInfrastructureError(
            "candidate_baseline_changed",
            "Candidate-visible baseline resources changed after row compilation",
        )
    if task_verification_digest(task) != task.verification_digest:
        raise VerificationInfrastructureError(
            "verification_inputs_changed",
            "Verification resources changed after row compilation",
        )


def _apply_oracle_outcomes(
    summaries: list[CheckResultSummary],
    verdict: OracleVerdict,
) -> list[CheckResultSummary]:
    check_ids = {summary.id for summary in summaries}
    outcome_ids = set(verdict.check_outcomes)
    if outcome_ids != check_ids:
        raise VerificationInfrastructureError(
            "oracle_protocol_error",
            "Oracle check outcomes do not match the declared verification checks",
        )
    output = []
    for summary in summaries:
        passed = verdict.check_outcomes[summary.id]
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
    task: BenchmarkTask,
    candidate: StoredCandidate | None,
    verdict: OracleVerdict,
    summaries: tuple[CheckResultSummary, ...],
) -> VerificationResultV2:
    return VerificationResultV2(
        task_id=task.id,
        benchmark_id=task.benchmark_id,
        status="passed" if verdict.passed else "failed",
        passed=verdict.passed,
        score=float(verdict.score),
        candidate_type=None if candidate is None else candidate.type,
        candidate_digest=None if candidate is None else candidate.digest,
        execution_profile=task.verification.execution_profile,
        manifest_digest=task.manifest_digest,
        row_digest=task.row_digest,
        image_digest=_image_digest(task.environment.image),
        baseline_digest=task.baseline_digest,
        verification_digest=task.verification_digest,
        checks=summaries,
        public_diagnostics=_bounded_public_diagnostics(verdict.public_diagnostics),
    )


def _infrastructure_result(
    task: BenchmarkTask,
    candidate: StoredCandidate | None,
    error: VerificationInfrastructureError,
) -> VerificationResultV2:
    return VerificationResultV2(
        task_id=task.id,
        benchmark_id=task.benchmark_id,
        status="infrastructure_error",
        passed=False,
        score=0.0,
        candidate_type=None if candidate is None else candidate.type,
        candidate_digest=None if candidate is None else candidate.digest,
        execution_profile=task.verification.execution_profile,
        manifest_digest=task.manifest_digest,
        row_digest=task.row_digest,
        image_digest=_image_digest(task.environment.image),
        baseline_digest=task.baseline_digest,
        verification_digest=task.verification_digest,
        infrastructure_error={"code": error.code, "message": error.public_message},
    )


def _bounded_public_diagnostics(value: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = canonical_json_bytes(value)
    except (TypeError, ValueError) as exc:
        raise VerificationInfrastructureError(
            "oracle_diagnostics_invalid", "Oracle public diagnostics are not JSON serializable"
        ) from exc
    if len(encoded) > 64 * 1024:
        raise VerificationInfrastructureError(
            "oracle_diagnostics_too_large", "Oracle public diagnostics exceeded their bound"
        )
    return value


def _image_digest(reference: str) -> str:
    if "@" in reference:
        return reference.rsplit("@", 1)[1]
    return reference
