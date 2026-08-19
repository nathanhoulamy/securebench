"""Isolated, one-case-at-a-time protocol verification."""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from securebench.candidates import CandidateReplayError, CandidateStore, StoredCandidate
from securebench.candidates.replay import replay_file_bundle
from securebench.sandboxes import CommandResult, DockerSandbox, HostSandbox
from securebench.sandboxes.base import MAX_COMMAND_OUTPUT_BYTES
from securebench.schemas.benchmark import ProtocolCheck
from securebench.tasks import BenchmarkTask
from securebench.verification.json_data import (
    canonical_json_bytes,
    json_digest,
    strict_json_loads,
)
from securebench.verification.models import (
    OracleCase,
    ProtocolCaseEvidence,
    VerificationInfrastructureError,
)
from securebench.verification.oracle import OracleSession
from securebench.workspaces.cleanup import remove_untrusted_tree
from securebench.workspaces.materialization import (
    VisibilityAwareMaterializer,
    docker_resource_mounts,
)


ADAPTER_ABI = "securebench.protocol-adapter/v1"
MAX_ADAPTER_COMMAND_PARTS = 32
MAX_ADAPTER_COMMAND_PART_BYTES = 4096
MAX_PROTOCOL_CHALLENGE_BYTES = 1024 * 1024
MAX_PROTOCOL_OBSERVATION_BYTES = MAX_COMMAND_OUTPUT_BYTES


@dataclass(frozen=True)
class AdapterManifest:
    command: tuple[str, ...]


class ProtocolCheckRunner:
    """Run protocol adapters in a fresh, offline Evaluation container per case."""

    def __init__(self, materializer: VisibilityAwareMaterializer | None = None) -> None:
        self.materializer = materializer or VisibilityAwareMaterializer()

    def evaluate(
        self,
        task: BenchmarkTask,
        candidate: StoredCandidate,
        store: CandidateStore,
        check: ProtocolCheck,
        oracle: OracleSession,
    ) -> tuple[ProtocolCaseEvidence, ...]:
        require_supported_protocol_features(check)
        manifest = load_adapter_manifest(task, check)
        evidence: list[ProtocolCaseEvidence] = []
        for case_index in range(check.challenge.max_cases):
            case = oracle.next_case(
                check.id,
                check.challenge.source,
                _case_bounds(check),
            )
            if case is None:
                break
            item = self._evaluate_case(task, candidate, store, check, manifest, case, case_index)
            oracle.evaluate_case(check.id, case.context, item)
            evidence.append(item)
        else:
            overflow = oracle.next_case(check.id, check.challenge.source, _case_bounds(check))
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
    ) -> tuple[ProtocolCaseEvidence, ...]:
        """Report the same candidate-production failure for every hidden case."""
        require_supported_protocol_features(check)
        evidence: list[ProtocolCaseEvidence] = []
        for case_index in range(check.challenge.max_cases):
            case = oracle.next_case(
                check.id,
                check.challenge.source,
                _case_bounds(check),
            )
            if case is None:
                break
            _validated_challenge(case, check)
            item = ProtocolCaseEvidence(
                check_id=check.id,
                case_index=case_index,
                challenge_digest=json_digest(case.challenge),
                status="candidate_error",
                error_code=code,
                error_message=message,
            )
            oracle.evaluate_case(check.id, case.context, item)
            evidence.append(item)
        else:
            overflow = oracle.next_case(check.id, check.challenge.source, _case_bounds(check))
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
        manifest: AdapterManifest,
        case: OracleCase,
        case_index: int,
    ) -> ProtocolCaseEvidence:
        challenge = _validated_challenge(case, check)
        evaluation_root = Path(tempfile.mkdtemp(prefix="securebench-evaluation-"))
        sandbox: DockerSandbox | None = None
        try:
            # Import lazily: the harness package imports execution-profile validation.
            from securebench.harnesses.shared import materialize_image_workdir

            materialize_image_workdir(task, evaluation_root)
            try:
                replay_file_bundle(
                    candidate,
                    store,
                    evaluation_root,
                    guest_root=task.environment.workdir,
                    expected_baseline_digest=task.baseline_digest,
                )
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
            result = sandbox.run(
                manifest.command,
                workdir=task.environment.workdir,
                timeout=float(check.limits.seconds_per_case),
                stdin=challenge + b"\n",
            )
            duration_ms = max(0, round((time.monotonic() - started) * 1000))
            return _adapter_evidence(check, case_index, case, result, duration_ms)
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


def load_adapter_manifest(task: BenchmarkTask, check: ProtocolCheck) -> AdapterManifest:
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
    try:
        manifest_text = (source / "adapter.yaml").read_text(encoding="utf-8")
    except OSError as exc:
        raise VerificationInfrastructureError(
            "adapter_manifest_missing", "Protocol adapter manifest is unavailable"
        ) from exc
    except UnicodeError as exc:
        raise VerificationInfrastructureError(
            "adapter_manifest_invalid", "Protocol adapter manifest is not valid UTF-8"
        ) from exc
    try:
        value = yaml.safe_load(manifest_text)
    except yaml.YAMLError as exc:
        raise VerificationInfrastructureError(
            "adapter_manifest_invalid", "Protocol adapter manifest is not valid YAML"
        ) from exc
    if not isinstance(value, dict) or set(value) != {"abi", "protocol", "command"}:
        raise VerificationInfrastructureError(
            "adapter_manifest_invalid", "Protocol adapter manifest has an invalid shape"
        )
    if value["abi"] != ADAPTER_ABI:
        raise VerificationInfrastructureError(
            "adapter_abi_unsupported", "Protocol adapter ABI is unsupported"
        )
    if value["protocol"] != check.protocol:
        raise VerificationInfrastructureError(
            "adapter_protocol_mismatch", "Protocol adapter does not implement the declared protocol"
        )
    command = value["command"]
    if (
        not isinstance(command, list)
        or not command
        or len(command) > MAX_ADAPTER_COMMAND_PARTS
        or not all(_valid_command_part(part) for part in command)
        or not command[0].strip()
    ):
        raise VerificationInfrastructureError(
            "adapter_manifest_invalid", "Protocol adapter command is invalid"
        )
    return AdapterManifest(
        command=tuple(_resolve_adapter_part(part, mount) for part in command),
    )


def require_supported_protocol_features(check: ProtocolCheck) -> None:
    if check.services:
        raise VerificationInfrastructureError(
            "protocol_services_unavailable",
            "Protocol check declares trusted services, which are not executable yet",
        )
    if check.artifacts:
        raise VerificationInfrastructureError(
            "protocol_artifacts_unavailable",
            "Protocol check declares returned artifacts, which are not executable yet",
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


def _valid_command_part(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "\x00" not in value
        and len(value.encode("utf-8")) <= MAX_ADAPTER_COMMAND_PART_BYTES
    )


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
            "adapter_manifest_invalid", "Protocol adapter command contains an unsafe path"
        )
    return str(mount / relative)


def _adapter_evidence(
    check: ProtocolCheck,
    case_index: int,
    case: OracleCase,
    result: CommandResult,
    duration_ms: int,
) -> ProtocolCaseEvidence:
    common = {
        "check_id": check.id,
        "case_index": case_index,
        "challenge_digest": json_digest(case.challenge),
        "exit_status": result.exit_code,
        "timed_out": result.timed_out,
        "duration_ms": duration_ms,
    }
    if result.timed_out:
        return ProtocolCaseEvidence(
            **common,
            status="candidate_error",
            error_code="adapter_timeout",
            error_message="Protocol adapter exceeded its per-case timeout",
        )
    if result.exit_code != 0:
        return ProtocolCaseEvidence(
            **common,
            status="candidate_error",
            error_code="adapter_failed",
            error_message="Protocol adapter exited unsuccessfully",
        )
    observation_bytes = (
        result.stdout_bytes
        if result.stdout_bytes is not None
        else len(result.stdout.encode("utf-8"))
    )
    if result.stdout_truncated or observation_bytes > check.limits.observation_bytes_per_case:
        return ProtocolCaseEvidence(
            **common,
            status="candidate_error",
            observation_bytes=observation_bytes,
            error_code="observation_too_large",
            error_message="Protocol observation exceeded its declared bound",
        )
    if not result.stdout_valid_utf8:
        return ProtocolCaseEvidence(
            **common,
            status="candidate_error",
            observation_bytes=observation_bytes,
            error_code="invalid_observation",
            error_message="Protocol adapter did not return valid UTF-8 JSON",
        )
    try:
        observation = strict_json_loads(result.stdout)
    except (UnicodeError, ValueError):
        return ProtocolCaseEvidence(
            **common,
            status="candidate_error",
            observation_bytes=observation_bytes,
            error_code="invalid_observation",
            error_message="Protocol adapter did not return one finite JSON value",
        )
    return ProtocolCaseEvidence(
        **common,
        status="observed",
        observation=observation,
        observation_bytes=observation_bytes,
    )


def _case_bounds(check: ProtocolCheck) -> dict[str, Any]:
    return {
        "max_cases": check.challenge.max_cases,
        "max_case_bytes": check.challenge.max_case_bytes,
    }


def _validated_challenge(case: OracleCase, check: ProtocolCheck) -> bytes:
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
    return challenge
