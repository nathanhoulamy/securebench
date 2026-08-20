"""Isolated, one-Challenge-at-a-time protocol verification."""

from __future__ import annotations

import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from yaml import YAMLError
from pydantic import ValidationError

from securebench.candidates import CandidateReplayError, CandidateStore, StoredCandidate
from securebench.candidates.replay import replay_candidate
from securebench.data_formats import strict_yaml_loads
from securebench.sandboxes import CommandResult, DockerSandbox, HostSandbox
from securebench.sandboxes.base import MAX_COMMAND_OUTPUT_BYTES
from securebench.schemas.benchmark import ProtocolCheck
from securebench.tasks import BenchmarkTask
from securebench.verification.json_data import (
    canonical_json_bytes,
    json_digest,
    strict_json_loads,
)
from securebench.verification.component_contracts import (
    ADAPTER_FORMAT_V2,
    AdapterManifestV2,
    TrustedHelperCatalog,
    adapter_request_v2,
    parse_adapter_response_v2,
    validate_json_value,
)
from securebench.verification.models import (
    ChallengeEvidence,
    OracleChallenge,
    VerificationInfrastructureError,
)
from securebench.verification.oracle import OracleSession
from securebench.workspaces.cleanup import remove_untrusted_tree
from securebench.workspaces.materialization import (
    VisibilityAwareMaterializer,
    docker_resource_mounts,
)


MAX_ADAPTER_MANIFEST_BYTES = 256 * 1024
MAX_TRUSTED_HELPER_SETTINGS_BYTES = 256 * 1024
MAX_ADAPTER_COMMAND_PARTS = 32
MAX_ADAPTER_COMMAND_PART_BYTES = 4096
MAX_PROTOCOL_CHALLENGE_BYTES = 1024 * 1024
MAX_PROTOCOL_OBSERVATION_BYTES = MAX_COMMAND_OUTPUT_BYTES


@dataclass(frozen=True)
class LoadedAdapter:
    """Validated Adapter v2 contract with its command resolved for Evaluation."""

    command: tuple[str, ...]
    contract: AdapterManifestV2


class ProtocolCheckRunner:
    """Run an Adapter in a fresh, offline Evaluation container per Challenge."""

    def __init__(
        self,
        materializer: VisibilityAwareMaterializer | None = None,
        trusted_helpers: TrustedHelperCatalog | None = None,
    ) -> None:
        self.materializer = materializer or VisibilityAwareMaterializer()
        self.trusted_helpers = trusted_helpers or TrustedHelperCatalog()

    def evaluate(
        self,
        task: BenchmarkTask,
        candidate: StoredCandidate,
        store: CandidateStore,
        check: ProtocolCheck,
        oracle: OracleSession,
    ) -> tuple[ChallengeEvidence, ...]:
        manifest = load_adapter_manifest(task, check)
        require_supported_protocol_features(
            check,
            manifest,
            self.trusted_helpers,
            task=task,
        )
        evidence: list[ChallengeEvidence] = []
        for challenge_index in range(check.challenge.max_cases):
            case = oracle.next_challenge(
                check.id,
                check.challenge.source,
                _case_bounds(check),
            )
            if case is None:
                break
            challenge_id = _new_identifier("challenge")
            item = self._evaluate_case(
                task,
                candidate,
                store,
                check,
                manifest,
                case,
                challenge_index,
                challenge_id,
            )
            oracle.evaluate_challenge(check.id, case.context, item)
            evidence.append(item)
        else:
            overflow = oracle.next_challenge(
                check.id, check.challenge.source, _case_bounds(check)
            )
            if overflow is not None:
                raise VerificationInfrastructureError(
                    "oracle_case_limit_exceeded",
                    "Oracle produced more challenges than the declared maximum",
                )
        if not evidence:
            raise VerificationInfrastructureError(
                "oracle_no_cases", "Oracle produced no challenges for a protocol check"
            )
        return tuple(evidence)

    def evaluate_candidate_error(
        self,
        check: ProtocolCheck,
        oracle: OracleSession,
        *,
        code: str,
        message: str,
    ) -> tuple[ChallengeEvidence, ...]:
        """Report the same candidate-production failure for every hidden case."""
        require_supported_protocol_features(check)
        evidence: list[ChallengeEvidence] = []
        for challenge_index in range(check.challenge.max_cases):
            case = oracle.next_challenge(
                check.id,
                check.challenge.source,
                _case_bounds(check),
            )
            if case is None:
                break
            _validated_challenge(case, check)
            item = ChallengeEvidence(
                check_id=check.id,
                challenge_id=_new_identifier("challenge"),
                evaluation_id=None,
                challenge_index=challenge_index,
                challenge_digest=json_digest(case.challenge),
                status="candidate_error",
                failure_source="candidate",
                failure_code=code,
                failure_message=message,
            )
            oracle.evaluate_challenge(check.id, case.context, item)
            evidence.append(item)
        else:
            overflow = oracle.next_challenge(
                check.id, check.challenge.source, _case_bounds(check)
            )
            if overflow is not None:
                raise VerificationInfrastructureError(
                    "oracle_case_limit_exceeded",
                    "Oracle produced more challenges than the declared maximum",
                )
        if not evidence:
            raise VerificationInfrastructureError(
                "oracle_no_cases", "Oracle produced no challenges for a protocol check"
            )
        return tuple(evidence)

    def _evaluate_case(
        self,
        task: BenchmarkTask,
        candidate: StoredCandidate,
        store: CandidateStore,
        check: ProtocolCheck,
        manifest: LoadedAdapter,
        case: OracleChallenge,
        challenge_index: int,
        challenge_id: str,
    ) -> ChallengeEvidence:
        _validated_challenge(case, check, manifest)
        evaluation_id = _new_identifier("evaluation")
        evaluation_root = Path(tempfile.mkdtemp(prefix="securebench-evaluation-"))
        sandbox: DockerSandbox | None = None
        try:
            # Import lazily: the harness package imports execution-profile validation.
            from securebench.harnesses.shared import materialize_image_workdir

            materialize_image_workdir(task, evaluation_root)
            try:
                replay_candidate(task, candidate, store, evaluation_root)
            except CandidateReplayError as exc:
                raise VerificationInfrastructureError(
                    "candidate_replay_failed", "Stored candidate could not be reconstructed"
                ) from exc
            staging = HostSandbox(root=evaluation_root)
            try:
                plan = self.materializer.materialize(task, staging, "evaluation_runtime")
            finally:
                staging.close()
            sandbox = DockerSandbox(
                image=task.environment.image,
                root=evaluation_root,
                persistent=False,
                network="none",
                read_only=True,
                mounts=docker_resource_mounts(plan),
                workspace_mount_target=task.environment.workdir,
            )
            started = time.monotonic()
            adapter_input = canonical_json_bytes(
                adapter_request_v2(
                    challenge_id=challenge_id,
                    evaluation_id=evaluation_id,
                    challenge=case.challenge,
                    trusted_helpers={},
                )
            )
            result = sandbox.run(
                manifest.command,
                workdir=task.environment.workdir,
                timeout=float(check.limits.seconds_per_case),
                stdin=adapter_input + b"\n",
            )
            duration_ms = max(0, round((time.monotonic() - started) * 1000))
            return _adapter_evidence(
                check,
                manifest.contract,
                challenge_index,
                challenge_id,
                evaluation_id,
                case,
                result,
                duration_ms,
            )
        finally:
            cleanup_error: Exception | None = None
            if sandbox is not None:
                try:
                    sandbox.close()
                except Exception as exc:
                    cleanup_error = exc
            try:
                remove_untrusted_tree(evaluation_root, image=task.environment.image)
            except Exception as exc:
                cleanup_error = cleanup_error or exc
            if cleanup_error is not None:
                raise VerificationInfrastructureError(
                    "evaluation_cleanup_failed", "Evaluation sandbox cleanup failed"
                ) from cleanup_error


def load_adapter_manifest(task: BenchmarkTask, check: ProtocolCheck) -> LoadedAdapter:
    """Load and validate the trusted runtime adapter selected by a protocol check."""
    resource = task.resources.resources.get(check.adapter)
    if resource is None or resource.kind != "directory" or not isinstance(resource.value, dict):
        raise VerificationInfrastructureError(
            "adapter_resource_invalid", "Protocol adapter must be a runtime directory resource"
        )
    source_value = resource.value.get("source_path")
    mount_value = resource.value.get("mount")
    if not isinstance(source_value, str) or not isinstance(mount_value, str):
        raise VerificationInfrastructureError(
            "adapter_resource_invalid", "Protocol adapter resource is invalid"
        )
    source = Path(source_value)
    mount = PurePosixPath(mount_value)
    if not source.is_absolute() or not source.is_dir() or source.is_symlink():
        raise VerificationInfrastructureError(
            "adapter_resource_invalid", "Protocol adapter directory is unavailable"
        )
    if not mount.is_absolute() or ".." in mount.parts or "\\" in mount_value:
        raise VerificationInfrastructureError(
            "adapter_resource_invalid", "Protocol adapter mount is invalid"
        )
    manifest_bytes = _read_bounded_file(
        source / "adapter.yaml",
        MAX_ADAPTER_MANIFEST_BYTES,
        unavailable_code="adapter_manifest_missing",
        unavailable_message="Protocol adapter manifest is unavailable",
        too_large_code="adapter_manifest_too_large",
        too_large_message="Protocol adapter manifest exceeded its bound",
        source="adapter",
    )
    try:
        manifest_text = manifest_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise VerificationInfrastructureError(
            "adapter_manifest_invalid",
            "Protocol adapter manifest is not valid UTF-8",
            source="adapter",
        ) from exc
    try:
        value = strict_yaml_loads(manifest_text)
    except YAMLError as exc:
        raise VerificationInfrastructureError(
            "adapter_manifest_invalid",
            "Protocol adapter manifest is not valid YAML",
            source="adapter",
        ) from exc
    if not isinstance(value, dict):
        raise VerificationInfrastructureError(
            "adapter_manifest_invalid",
            "Protocol adapter manifest has an invalid shape",
            source="adapter",
        )
    if value.get("format") != ADAPTER_FORMAT_V2:
        raise VerificationInfrastructureError(
            "adapter_format_unsupported",
            "Protocol Adapter must use the securebench.adapter/v2 format",
            source="adapter",
        )
    try:
        contract = AdapterManifestV2.model_validate(value, strict=False)
    except (TypeError, ValueError, ValidationError) as exc:
        raise VerificationInfrastructureError(
            "adapter_manifest_invalid",
            "Protocol Adapter v2 manifest is invalid",
            source="adapter",
        ) from exc
    if contract.protocol != check.protocol:
        raise VerificationInfrastructureError(
            "adapter_protocol_mismatch",
            "Protocol Adapter does not implement the declared protocol",
            source="adapter",
        )
    command = contract.command
    _validate_adapter_command(command)
    return LoadedAdapter(
        command=tuple(_resolve_adapter_part(part, mount) for part in command),
        contract=contract,
    )


def require_supported_protocol_features(
    check: ProtocolCheck,
    manifest: LoadedAdapter | None = None,
    trusted_helpers: TrustedHelperCatalog | None = None,
    *,
    task: BenchmarkTask | None = None,
) -> None:
    if check.trusted_helpers and manifest is None:
        raise VerificationInfrastructureError(
            "trusted_helpers_unavailable",
            "Protocol check declares Trusted Helpers without an adapter v2 contract",
        )
    if check.output_artifacts and manifest is None:
        raise VerificationInfrastructureError(
            "output_artifacts_unavailable",
            "Protocol check declares output artifacts without an adapter v2 contract",
        )
    if check.limits.observation_bytes_per_case > MAX_PROTOCOL_OBSERVATION_BYTES:
        raise VerificationInfrastructureError(
            "protocol_observation_bound_unsupported",
            "Protocol observation bound exceeds the Evaluation output capacity",
        )
    if check.challenge.max_case_bytes > MAX_PROTOCOL_CHALLENGE_BYTES:
        raise VerificationInfrastructureError(
            "protocol_challenge_bound_unsupported",
            "Protocol challenge bound exceeds the Oracle transport capacity",
        )
    if manifest is None:
        return
    contract = manifest.contract
    _validate_adapter_maximums(check, contract)
    _validate_evaluation_participants(contract)
    _validate_trusted_helper_contracts(
        check,
        contract,
        trusted_helpers or TrustedHelperCatalog(),
        task=task,
    )
    _validate_output_artifact_contracts(check, contract)


def _validate_adapter_command(command: Any) -> None:
    if (
        not isinstance(command, (list, tuple))
        or not command
        or len(command) > MAX_ADAPTER_COMMAND_PARTS
        or not all(_valid_command_part(part) for part in command)
        or not command[0].strip()
    ):
        raise VerificationInfrastructureError(
            "adapter_manifest_invalid",
            "Protocol adapter command is invalid",
            source="adapter",
        )


def _validate_adapter_maximums(check: ProtocolCheck, contract: AdapterManifestV2) -> None:
    maximums = contract.maximums
    if (
        check.challenge.max_case_bytes > maximums.challenge_bytes
        or check.limits.observation_bytes_per_case > maximums.observation_bytes
        or check.limits.seconds_per_case > maximums.seconds_per_challenge
    ):
        raise VerificationInfrastructureError(
            "adapter_maximum_exceeded",
            "Protocol check exceeds the adapter's declared maximums",
        )


def _validate_evaluation_participants(contract: AdapterManifestV2) -> None:
    participants = contract.evaluation_participants
    if (
        len(participants) != 1
        or participants[0].name != "candidate"
        or participants[0].type != "candidate"
        or participants[0].instances != 1
    ):
        raise VerificationInfrastructureError(
            "evaluation_participants_unsupported",
            "This execution profile supports exactly one Candidate participant",
        )


def _validate_trusted_helper_contracts(
    check: ProtocolCheck,
    contract: AdapterManifestV2,
    catalog: TrustedHelperCatalog,
    *,
    task: BenchmarkTask | None,
) -> None:
    declared = {helper.name: helper for helper in check.trusted_helpers}
    required = {helper.name: helper for helper in contract.uses_trusted_helpers}
    if set(declared) != set(required) or any(
        declared[name].type != required[name].type for name in declared.keys() & required.keys()
    ):
        raise VerificationInfrastructureError(
            "trusted_helper_contract_mismatch",
            "Protocol check Trusted Helpers do not match the adapter contract",
        )
    for helper in check.trusted_helpers:
        helper_contract = catalog.validate_declaration(helper)
        if task is not None:
            catalog.validate_settings(
                helper_contract,
                _trusted_helper_settings(task, helper.settings),
            )
    if check.trusted_helpers:
        raise VerificationInfrastructureError(
            "trusted_helper_runtime_unavailable",
            "Trusted Helper contracts are defined but their runtime is not implemented yet",
        )


def _validate_output_artifact_contracts(
    check: ProtocolCheck,
    contract: AdapterManifestV2,
) -> None:
    requested = {artifact.name: artifact for artifact in check.output_artifacts}
    declared = {artifact.name: artifact for artifact in contract.output_artifacts}
    if not set(requested).issubset(declared):
        raise VerificationInfrastructureError(
            "output_artifact_contract_mismatch",
            "Protocol check requests output artifacts not declared by the adapter",
        )
    for name, artifact in requested.items():
        maximums = declared[name].maximum_limits
        limits = artifact.limits
        if any(
            value is not None and (maximum is None or value > maximum)
            for value, maximum in (
                (limits.max_bytes, maximums.max_bytes),
                (limits.max_files, maximums.max_files),
                (limits.max_total_bytes, maximums.max_total_bytes),
            )
        ):
            raise VerificationInfrastructureError(
                "output_artifact_maximum_exceeded",
                f"Output artifact {name!r} exceeds the adapter's declared maximums",
            )
    if check.output_artifacts:
        raise VerificationInfrastructureError(
            "output_artifact_collection_unavailable",
            "Output Artifact contracts are defined but collection is not implemented yet",
        )


def _trusted_helper_settings(task: BenchmarkTask, reference: str | None) -> Any:
    if reference is None:
        return {}
    resource = task.resources.resources.get(reference)
    if resource is None or resource.kind != "file" or not isinstance(resource.value, dict):
        raise VerificationInfrastructureError(
            "trusted_helper_settings_invalid",
            "Trusted Helper settings must reference one host-only file",
            source="trusted_helper",
        )
    source = resource.value.get("source_path")
    if not isinstance(source, str):
        raise VerificationInfrastructureError(
            "trusted_helper_settings_invalid",
            "Trusted Helper settings are unavailable",
            source="trusted_helper",
        )
    content = _read_bounded_file(
        Path(source),
        MAX_TRUSTED_HELPER_SETTINGS_BYTES,
        unavailable_code="trusted_helper_settings_invalid",
        unavailable_message="Trusted Helper settings are unavailable",
        too_large_code="trusted_helper_settings_too_large",
        too_large_message="Trusted Helper settings exceeded their bound",
        source="trusted_helper",
    )
    try:
        return strict_yaml_loads(content.decode("utf-8"))
    except (UnicodeError, YAMLError) as exc:
        raise VerificationInfrastructureError(
            "trusted_helper_settings_invalid",
            "Trusted Helper settings are not valid YAML",
            source="trusted_helper",
        ) from exc


def _valid_command_part(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "\x00" not in value
        and len(value.encode("utf-8")) <= MAX_ADAPTER_COMMAND_PART_BYTES
    )


def _read_bounded_file(
    path: Path,
    maximum_bytes: int,
    *,
    unavailable_code: str,
    unavailable_message: str,
    too_large_code: str,
    too_large_message: str,
    source: Literal["adapter", "trusted_helper", "framework"],
) -> bytes:
    try:
        with path.open("rb") as stream:
            content = stream.read(maximum_bytes + 1)
    except OSError as exc:
        raise VerificationInfrastructureError(
            unavailable_code,
            unavailable_message,
            source=source,
        ) from exc
    if len(content) > maximum_bytes:
        raise VerificationInfrastructureError(
            too_large_code,
            too_large_message,
            source=source,
        )
    return content


def _resolve_adapter_part(value: str, mount: PurePosixPath) -> str:
    if not value.startswith("./"):
        return value
    relative = PurePosixPath(value[2:])
    if (
        str(relative) in {"", "."}
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in value
    ):
        raise VerificationInfrastructureError(
            "adapter_manifest_invalid",
            "Protocol adapter command contains an unsafe path",
            source="adapter",
        )
    return str(mount / relative)


def _adapter_evidence(
    check: ProtocolCheck,
    contract: AdapterManifestV2,
    challenge_index: int,
    challenge_id: str,
    evaluation_id: str,
    challenge: OracleChallenge,
    result: CommandResult,
    duration_ms: int,
) -> ChallengeEvidence:
    if result.timed_out:
        raise VerificationInfrastructureError(
            "adapter_timeout",
            "Reviewed protocol Adapter exceeded its per-Challenge timeout",
            source="adapter",
        )
    if result.exit_code != 0:
        raise VerificationInfrastructureError(
            "adapter_failed",
            "Reviewed protocol Adapter exited unsuccessfully",
            source="adapter",
        )
    response_bytes = (
        result.stdout_bytes
        if result.stdout_bytes is not None
        else len(result.stdout.encode("utf-8"))
    )
    if result.stdout_truncated or response_bytes > check.limits.observation_bytes_per_case:
        raise VerificationInfrastructureError(
            "adapter_response_too_large",
            "Reviewed protocol Adapter response exceeded its bound",
            source="adapter",
        )
    if not result.stdout_valid_utf8:
        raise VerificationInfrastructureError(
            "adapter_response_invalid",
            "Reviewed protocol Adapter returned invalid UTF-8",
            source="adapter",
        )
    try:
        response = parse_adapter_response_v2(strict_json_loads(result.stdout))
    except (UnicodeError, ValueError) as exc:
        raise VerificationInfrastructureError(
            "adapter_response_invalid",
            "Reviewed protocol Adapter returned an invalid response",
            source="adapter",
        ) from exc
    common = {
        "check_id": check.id,
        "challenge_id": challenge_id,
        "evaluation_id": evaluation_id,
        "challenge_index": challenge_index,
        "challenge_digest": json_digest(challenge.challenge),
        "exit_status": result.exit_code,
        "duration_ms": duration_ms,
        "observation_bytes": response_bytes,
    }
    if response.status == "candidate_error":
        return ChallengeEvidence(
            **common,
            status="candidate_error",
            failure_source="candidate",
            failure_code=response.failure_code,
            failure_message=response.failure_message,
        )
    try:
        validate_json_value(contract.observation_schema, response.observation)
    except ValueError as exc:
        raise VerificationInfrastructureError(
            "adapter_observation_schema_mismatch",
            "Reviewed protocol Adapter returned an Observation outside its contract",
            source="adapter",
        ) from exc
    return ChallengeEvidence(
        **common,
        status="observed",
        observation=response.observation,
    )


def _case_bounds(check: ProtocolCheck) -> dict[str, Any]:
    return {
        "max_cases": check.challenge.max_cases,
        "max_case_bytes": check.challenge.max_case_bytes,
    }


def _validated_challenge(
    case: OracleChallenge,
    check: ProtocolCheck,
    manifest: LoadedAdapter | None = None,
) -> bytes:
    try:
        challenge = canonical_json_bytes(case.challenge)
    except (TypeError, ValueError) as exc:
        raise VerificationInfrastructureError(
            "oracle_protocol_error", "Oracle case was not finite JSON data"
        ) from exc
    if len(challenge) > check.challenge.max_case_bytes:
        raise VerificationInfrastructureError(
            "oracle_case_too_large", "Oracle challenge exceeded its declared bound"
        )
    if manifest is not None:
        try:
            validate_json_value(manifest.contract.challenge_schema, case.challenge)
        except ValueError as exc:
            raise VerificationInfrastructureError(
                "oracle_challenge_schema_mismatch",
                "Oracle Challenge does not match the Adapter contract",
            ) from exc
    return challenge


def _new_identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"
