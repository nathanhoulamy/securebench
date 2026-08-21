"""Collection of Adapter-declared Output Artifacts from one Evaluation."""

from __future__ import annotations

from pathlib import Path

from securebench.schemas.benchmark import OutputArtifactSpec, ProtocolCheck
from securebench.verification.component_contracts import AdapterManifestV2, OutputArtifactContract
from securebench.verification.models import (
    CandidateObservationError,
    OutputArtifactEvidence,
    ParserRejected,
    VerificationInfrastructureError,
)
from securebench.verification.parsers import ParserRegistry, default_parser_registry
from securebench.verification.passive_files import PassiveFileObservation, observe_bounded_path


class OutputArtifactCollector:
    """Passively collect and parse artifacts after an Evaluation process exits."""

    def __init__(self, parsers: ParserRegistry | None = None) -> None:
        self.parsers = parsers or default_parser_registry()

    def collect(
        self,
        evaluation_root: Path,
        check: ProtocolCheck,
        contract: AdapterManifestV2,
        *,
        challenge_id: str,
        evaluation_id: str,
    ) -> tuple[OutputArtifactEvidence, ...]:
        declarations = {artifact.name: artifact for artifact in contract.output_artifacts}
        if any(
            artifact.name not in declarations
            or not _declaration_supports(artifact, declarations[artifact.name])
            for artifact in check.output_artifacts
        ):
            raise VerificationInfrastructureError(
                "output_artifact_contract_mismatch",
                "Output Artifact collection does not match the Adapter contract",
                source="adapter",
            )
        return tuple(
            self._collect_one(
                evaluation_root,
                artifact,
                declarations[artifact.name],
                challenge_id=challenge_id,
                evaluation_id=evaluation_id,
            )
            for artifact in check.output_artifacts
        )

    def _collect_one(
        self,
        evaluation_root: Path,
        artifact: OutputArtifactSpec,
        declaration: OutputArtifactContract,
        *,
        challenge_id: str,
        evaluation_id: str,
    ) -> OutputArtifactEvidence:
        observed: PassiveFileObservation | None = None
        try:
            observed = observe_bounded_path(
                evaluation_root,
                declaration.path,
                artifact.limits,
                subject=f"Output artifact {artifact.name!r}",
            )
        except CandidateObservationError as exc:
            return _candidate_error(
                artifact,
                challenge_id,
                evaluation_id,
                exc,
            )
        except Exception as exc:
            raise VerificationInfrastructureError(
                "output_artifact_collection_failed",
                "Output Artifact could not be collected safely",
                source="framework",
            ) from exc
        try:
            if observed.kind == "regular_file":
                if not isinstance(observed.value, bytes):
                    raise TypeError("regular-file observation did not contain bytes")
                parsed = self.parsers.parse_bytes(artifact.parser, observed.value)
            else:
                if not isinstance(observed.value, dict):
                    raise TypeError("tree observation did not contain a manifest")
                parsed = self.parsers.parse_tree(artifact.parser, observed.value)
        except ParserRejected as exc:
            return _candidate_error(
                artifact,
                challenge_id,
                evaluation_id,
                exc,
                observed=observed,
            )
        except Exception as exc:
            raise VerificationInfrastructureError(
                "output_artifact_parser_failed",
                "Registered Output Artifact parser violated its contract",
                source="framework",
            ) from exc
        try:
            return OutputArtifactEvidence(
                name=artifact.name,
                challenge_id=challenge_id,
                evaluation_id=evaluation_id,
                status="observed",
                digest=observed.digest,
                size=observed.size,
                parser=artifact.parser,
                parsed_value=parsed,
            )
        except (TypeError, ValueError) as exc:
            raise VerificationInfrastructureError(
                "output_artifact_parser_failed",
                "Registered Output Artifact parser returned invalid evidence",
                source="framework",
            ) from exc


def _candidate_error(
    artifact: OutputArtifactSpec,
    challenge_id: str,
    evaluation_id: str,
    error: CandidateObservationError | ParserRejected,
    *,
    observed: PassiveFileObservation | None = None,
) -> OutputArtifactEvidence:
    return OutputArtifactEvidence(
        name=artifact.name,
        challenge_id=challenge_id,
        evaluation_id=evaluation_id,
        status="candidate_error",
        digest=None if observed is None else observed.digest,
        size=None if observed is None else observed.size,
        parser=artifact.parser,
        failure_code=error.code,
        failure_message=error.public_message,
    )


def _declaration_supports(
    artifact: OutputArtifactSpec,
    declaration: OutputArtifactContract,
) -> bool:
    expected_kind = (
        "regular_file" if artifact.limits.max_bytes is not None else "directory_tree"
    )
    if declaration.kind != expected_kind:
        return False
    return all(
        value is None or (maximum is not None and value <= maximum)
        for value, maximum in (
            (artifact.limits.max_bytes, declaration.maximum_limits.max_bytes),
            (artifact.limits.max_files, declaration.maximum_limits.max_files),
            (
                artifact.limits.max_total_bytes,
                declaration.maximum_limits.max_total_bytes,
            ),
        )
    )
