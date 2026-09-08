"""Reviewed Trusted Helper catalog and per-Evaluation runtime lifecycle."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from yaml import YAMLError

from securebench.data_formats import strict_yaml_loads
from securebench.docker_network import ISOLATED_BRIDGE_ARGUMENTS, validate_private_network
from securebench.errors import ConfigError
from securebench.sandboxes import (
    CommandResult,
    DockerSandbox,
    DockerSandboxError,
    ScheduledContainerSignal,
)
from securebench.schemas.benchmark import ProtocolCheck, TrustedHelperSpec
from securebench.tasks import BenchmarkTask
from securebench.verification.component_contracts import (
    TRUSTED_HELPER_CONTRACT_FORMAT_V1,
    JsonValueSchema,
    TrustedHelperCatalog,
    TrustedHelperContract,
)
from securebench.verification.json_data import canonical_json_bytes, strict_json_loads
from securebench.verification.models import (
    TrustedHelperEvidence,
    VerificationInfrastructureError,
)
from securebench.workspaces.cleanup import remove_untrusted_tree


HTTP_REQUEST_RECORDER_TYPE = "securebench.http-request-recorder/v1"
APPEND_ONLY_EVENT_LEDGER_TYPE = "securebench.append-only-event-ledger/v1"
PROCESS_SUPERVISOR_TYPE = "securebench.process-supervisor/v1"
HTTP_REQUEST_RECORDER_IMAGE = (
    "python:3.11-slim@sha256:"
    "9c900dea9e8fb7e16277c179b555cc72d29a352dbc33cff48ad5a0412fd5bfc7"
)
HTTP_REQUEST_RECORDER_PORT = 8080
EVENT_LEDGER_IMAGE = HTTP_REQUEST_RECORDER_IMAGE
EVENT_LEDGER_PORT = 8080
MAX_TRUSTED_HELPER_SETTINGS_BYTES = 256 * 1024
MAX_RECORDER_RECORDS = 128
MAX_RECORDER_BODY_BYTES = 65536
MAX_RECORDER_HEADER_BYTES = 32768
MAX_RECORDER_RESPONSE_BYTES = 16384
MAX_RECORDER_EVIDENCE_BYTES = 32 * 1024 * 1024
MAX_RECORDER_READY_BYTES = 1024
MAX_EVENT_LEDGER_RECORDS = 256
MAX_EVENT_LEDGER_EVENT_BYTES = 4096
MAX_EVENT_LEDGER_EVIDENCE_BYTES = 4 * 1024 * 1024
MAX_PROCESS_SUPERVISOR_SIGNALS = 8
MAX_PROCESS_SUPERVISOR_DELAY_MS = 60_000
HELPER_START_TIMEOUT_SECONDS = 10.0
DOCKER_OPERATION_TIMEOUT_SECONDS = 30.0
INTERRUPTED_HELPER_CLEANUP_ATTEMPTS = 20
INTERRUPTED_HELPER_CLEANUP_INTERVAL_SECONDS = 0.1
RECORDED_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9a-z-]+")
EVENT_LEDGER_EVENT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
EVENT_LEDGER_NONCE = re.compile(r"[A-Za-z0-9_-]{1,128}")
PROCESS_SUPERVISOR_SIGNALS = {
    "SIGHUP",
    "SIGINT",
    "SIGTERM",
    "SIGUSR1",
    "SIGUSR2",
}


def _object_schema(
    properties: dict[str, dict[str, Any] | JsonValueSchema],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "max_fields": max(1, len(properties)),
    }


def http_request_recorder_contract() -> TrustedHelperContract:
    """Return the immutable reviewed contract for the built-in recorder."""
    header_schema = _object_schema(
        {
            "name": {"type": "string", "max_utf8_bytes": 256},
            "value": {"type": "string", "max_utf8_bytes": MAX_RECORDER_HEADER_BYTES},
        },
        required=("name", "value"),
    )
    request_schema = _object_schema(
        {
            "sequence": {"type": "integer"},
            "challenge_id": {"type": "string", "max_utf8_bytes": 128},
            "evaluation_id": {"type": "string", "max_utf8_bytes": 128},
            "method": {"type": "string", "max_utf8_bytes": 32},
            "target": {"type": "string", "max_utf8_bytes": 8192},
            "target_truncated": {"type": "boolean"},
            "headers": {
                "type": "array",
                "items": header_schema,
                "max_items": 128,
            },
            "header_bytes": {"type": "integer"},
            "headers_truncated": {"type": "boolean"},
            "body_base64": {
                "type": "string",
                "max_utf8_bytes": ((MAX_RECORDER_BODY_BYTES + 2) // 3) * 4,
            },
            "body_bytes": {"type": "integer"},
            "declared_body_bytes": {"type": "integer"},
            "body_sha256": {"type": "string", "max_utf8_bytes": 71},
            "body_truncated": {"type": "boolean"},
            "authenticated": {"type": "boolean"},
            "path_matched": {"type": "boolean"},
            "response_status": {"type": "integer"},
        },
        required=(
            "sequence",
            "challenge_id",
            "evaluation_id",
            "method",
            "target",
            "target_truncated",
            "headers",
            "header_bytes",
            "headers_truncated",
            "body_base64",
            "body_bytes",
            "declared_body_bytes",
            "body_sha256",
            "body_truncated",
            "authenticated",
            "path_matched",
            "response_status",
        ),
    )
    return TrustedHelperContract.model_validate(
        {
            "format": TRUSTED_HELPER_CONTRACT_FORMAT_V1,
            "type": HTTP_REQUEST_RECORDER_TYPE,
            "capabilities": ["record_requests"],
            "helper_access": "http",
            "settings_schema": _object_schema(
                {
                    "path": {"type": "string", "max_utf8_bytes": 2048},
                    "response_status": {"type": "integer"},
                    "response_body": {
                        "type": "string",
                        "max_utf8_bytes": MAX_RECORDER_RESPONSE_BYTES,
                    },
                }
            ),
            "limits_schema": _object_schema(
                {
                    "max_requests": {"type": "integer"},
                    "max_body_bytes": {"type": "integer"},
                    "max_header_bytes": {"type": "integer"},
                },
                required=("max_requests", "max_body_bytes"),
            ),
            "maximum_limits": {
                "max_requests": MAX_RECORDER_RECORDS,
                "max_body_bytes": MAX_RECORDER_BODY_BYTES,
                "max_header_bytes": MAX_RECORDER_HEADER_BYTES,
            },
            "evidence_schema": _object_schema(
                {
                    "requests": {
                        "type": "array",
                        "items": request_schema,
                        "max_items": MAX_RECORDER_RECORDS,
                    }
                },
                required=("requests",),
            ),
            "reset": "fresh_per_evaluation",
            "credentials": "fresh_per_evaluation",
        },
        strict=False,
    )


def append_only_event_ledger_contract() -> TrustedHelperContract:
    """Return the immutable contract for the timestamped append-only ledger."""
    event_schema = _object_schema(
        {
            "sequence": {"type": "integer"},
            "elapsed_us": {"type": "integer"},
            "challenge_id": {"type": "string", "max_utf8_bytes": 128},
            "evaluation_id": {"type": "string", "max_utf8_bytes": 128},
            "method": {"type": "string", "max_utf8_bytes": 16},
            "target": {"type": "string", "max_utf8_bytes": 2048},
            "target_truncated": {"type": "boolean"},
            "path_matched": {"type": "boolean"},
            "authenticated": {"type": "boolean"},
            "content_type_valid": {"type": "boolean"},
            "header_bytes": {"type": "integer"},
            "body_bytes": {"type": "integer"},
            "declared_body_bytes": {"type": "integer"},
            "body_base64": {
                "type": "string",
                "max_utf8_bytes": ((MAX_EVENT_LEDGER_EVENT_BYTES + 2) // 3) * 4,
            },
            "body_sha256": {"type": "string", "max_utf8_bytes": 71},
            "body_truncated": {"type": "boolean"},
            "event_valid": {"type": "boolean"},
            "accepted": {"type": "boolean"},
            "nonce": {"type": "string", "max_utf8_bytes": 128},
            "event": {"type": "string", "max_utf8_bytes": 64},
            "data": {"type": "string", "max_utf8_bytes": MAX_EVENT_LEDGER_EVENT_BYTES},
            "response_status": {"type": "integer"},
        },
        required=(
            "sequence",
            "elapsed_us",
            "challenge_id",
            "evaluation_id",
            "method",
            "target",
            "target_truncated",
            "path_matched",
            "authenticated",
            "content_type_valid",
            "header_bytes",
            "body_bytes",
            "declared_body_bytes",
            "body_base64",
            "body_sha256",
            "body_truncated",
            "event_valid",
            "accepted",
            "nonce",
            "event",
            "data",
            "response_status",
        ),
    )
    return TrustedHelperContract.model_validate(
        {
            "format": TRUSTED_HELPER_CONTRACT_FORMAT_V1,
            "type": APPEND_ONLY_EVENT_LEDGER_TYPE,
            "capabilities": ["append_nonce_event", "record_monotonic_time"],
            "helper_access": "http",
            "settings_schema": _object_schema(
                {"path": {"type": "string", "max_utf8_bytes": 2048}}
            ),
            "limits_schema": _object_schema(
                {
                    "max_events": {"type": "integer"},
                    "max_event_bytes": {"type": "integer"},
                },
                required=("max_events", "max_event_bytes"),
            ),
            "maximum_limits": {
                "max_events": MAX_EVENT_LEDGER_RECORDS,
                "max_event_bytes": MAX_EVENT_LEDGER_EVENT_BYTES,
            },
            "evidence_schema": _object_schema(
                {
                    "events": {
                        "type": "array",
                        "items": event_schema,
                        "max_items": MAX_EVENT_LEDGER_RECORDS,
                    }
                },
                required=("events",),
            ),
            "reset": "fresh_per_evaluation",
            "credentials": "fresh_per_evaluation",
        },
        strict=False,
    )


def process_supervisor_contract() -> TrustedHelperContract:
    """Return the immutable host-only process supervision contract."""
    configured_signal = _object_schema(
        {
            "signal": {"type": "string", "max_utf8_bytes": 16},
            "after_ms": {"type": "integer"},
        },
        required=("signal", "after_ms"),
    )
    observed_signal = _object_schema(
        {
            "sequence": {"type": "integer"},
            "signal": {"type": "string", "max_utf8_bytes": 16},
            "scheduled_after_ms": {"type": "integer"},
            "attempted_after_ms": {"type": "integer"},
            "delivered": {"type": "boolean"},
        },
        required=(
            "sequence",
            "signal",
            "scheduled_after_ms",
            "attempted_after_ms",
            "delivered",
        ),
    )
    process = _object_schema(
        {
            "container_started": {"type": "boolean"},
            "started_after_ms": {"type": "integer"},
            "duration_ms": {"type": "integer"},
            "exit_code": {"type": "integer"},
            "timed_out": {"type": "boolean"},
        },
        required=(
            "container_started",
            "started_after_ms",
            "duration_ms",
            "exit_code",
            "timed_out",
        ),
    )
    return TrustedHelperContract.model_validate(
        {
            "format": TRUSTED_HELPER_CONTRACT_FORMAT_V1,
            "type": PROCESS_SUPERVISOR_TYPE,
            "capabilities": [
                "deliver_signals",
                "inspect_process_lifecycle",
                "inspect_monotonic_timing",
            ],
            "helper_access": "none",
            "settings_schema": _object_schema(
                {
                    "signals": {
                        "type": "array",
                        "items": configured_signal,
                        "max_items": MAX_PROCESS_SUPERVISOR_SIGNALS,
                    }
                }
            ),
            "limits_schema": _object_schema(
                {
                    "max_signals": {"type": "integer"},
                    "max_delay_ms": {"type": "integer"},
                },
                required=("max_signals", "max_delay_ms"),
            ),
            "maximum_limits": {
                "max_signals": MAX_PROCESS_SUPERVISOR_SIGNALS,
                "max_delay_ms": MAX_PROCESS_SUPERVISOR_DELAY_MS,
            },
            "evidence_schema": _object_schema(
                {
                    "process": process,
                    "signals": {
                        "type": "array",
                        "items": observed_signal,
                        "max_items": MAX_PROCESS_SUPERVISOR_SIGNALS,
                    },
                },
                required=("process", "signals"),
            ),
            "reset": "fresh_per_evaluation",
            "credentials": "none",
        },
        strict=False,
    )


def default_trusted_helper_catalog() -> TrustedHelperCatalog:
    """Return the framework-owned catalog of implemented, reviewed helpers."""
    recorder = http_request_recorder_contract()
    ledger = append_only_event_ledger_contract()
    supervisor = process_supervisor_contract()
    return TrustedHelperCatalog(
        (recorder, ledger, supervisor),
        runtime_factories={
            HTTP_REQUEST_RECORDER_TYPE: HttpRequestRecorderRuntime,
            APPEND_ONLY_EVENT_LEDGER_TYPE: AppendOnlyEventLedgerRuntime,
            PROCESS_SUPERVISOR_TYPE: ProcessSupervisorRuntime,
        },
    )


def load_trusted_helper_settings(task: BenchmarkTask, reference: str | None) -> Any:
    """Load one bounded host-only Trusted Helper settings document."""
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
    try:
        with Path(source).open("rb") as stream:
            content = stream.read(MAX_TRUSTED_HELPER_SETTINGS_BYTES + 1)
    except OSError as exc:
        raise VerificationInfrastructureError(
            "trusted_helper_settings_invalid",
            "Trusted Helper settings are unavailable",
            source="trusted_helper",
        ) from exc
    if len(content) > MAX_TRUSTED_HELPER_SETTINGS_BYTES:
        raise VerificationInfrastructureError(
            "trusted_helper_settings_too_large",
            "Trusted Helper settings exceeded their bound",
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


class HttpRequestRecorderRuntime:
    """One disposable HTTP recorder bound to one Evaluation and credential."""

    @staticmethod
    def validate_settings(value: Any) -> None:
        if not isinstance(value, dict):
            raise ValueError("settings must be an object")
        path = value.get("path", "/")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or "\\" in path
            or any(character in path for character in ("?", "#", "\x00", "\r", "\n"))
            or any(ord(character) < 0x21 or ord(character) > 0x7E for character in path)
        ):
            raise ValueError("path must be one absolute HTTP origin-form path")
        status = value.get("response_status", 204)
        if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status <= 599:
            raise ValueError("response_status must be an HTTP status code")
        if status in {204, 205, 304} and value.get("response_body", ""):
            raise ValueError("response_body must be empty for a bodyless HTTP status")

    def __init__(
        self,
        *,
        helper: TrustedHelperSpec,
        contract: TrustedHelperContract,
        settings: Any,
        challenge_id: str,
        evaluation_id: str,
        network: str,
    ) -> None:
        self.helper = helper
        self.contract = contract
        self.settings = settings
        self.challenge_id = challenge_id
        self.evaluation_id = evaluation_id
        self.network = network
        self.container_name = f"securebench-helper-{uuid.uuid4().hex}"
        self.root = Path(tempfile.mkdtemp(prefix="securebench-trusted-helper-"))
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(mode=0o700)
        self.token = secrets.token_urlsafe(32)
        self.started = False

    def start(self, alias: str) -> dict[str, str]:
        config = {
            "challenge_id": self.challenge_id,
            "evaluation_id": self.evaluation_id,
            "settings": self.settings,
            "limits": self.helper.limits,
        }
        config_path = self.root / "config.json"
        credential_path = self.root / "credential"
        config_path.write_bytes(canonical_json_bytes(config))
        credential_path.write_text(self.token, encoding="ascii")
        config_path.chmod(0o600)
        credential_path.chmod(0o600)
        script_path = Path(__file__).with_name("http_request_recorder_server.py").resolve()
        command = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self.container_name,
            "--network",
            self.network,
            "--network-alias",
            alias,
            "--cap-drop",
            "ALL",
            "--cap-add",
            "DAC_OVERRIDE",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--memory",
            "128m",
            "--pids-limit",
            "64",
            "--security-opt",
            "no-new-privileges:true",
            "--label",
            "securebench.role=trusted-helper",
            "--log-driver",
            "none",
            "--mount",
            f"type=bind,source={script_path},target=/opt/securebench/recorder.py,readonly",
            "--mount",
            f"type=bind,source={config_path},target=/opt/securebench/config.json,readonly",
            "--mount",
            f"type=bind,source={credential_path},target=/opt/securebench/credential,readonly",
            "--mount",
            f"type=bind,source={self.state_dir},target=/var/lib/securebench",
            HTTP_REQUEST_RECORDER_IMAGE,
            "python3",
            "/opt/securebench/recorder.py",
            "--host",
            "0.0.0.0",
            "--port",
            str(HTTP_REQUEST_RECORDER_PORT),
            "--config",
            "/opt/securebench/config.json",
            "--credential",
            "/opt/securebench/credential",
            "--state-dir",
            "/var/lib/securebench",
        ]
        # Claim cleanup ownership before invoking Docker: a timed-out CLI may
        # still have created the named container in the daemon.
        self.started = True
        try:
            _run_docker(command, "trusted_helper_start_failed", "Trusted Helper failed to start")
            deadline = time.monotonic() + HELPER_START_TIMEOUT_SECONDS
            ready_path = self.state_dir / "ready.json"
            while time.monotonic() < deadline:
                if ready_path.is_file() and not ready_path.is_symlink():
                    try:
                        with ready_path.open("rb") as stream:
                            ready_bytes = stream.read(MAX_RECORDER_READY_BYTES + 1)
                        if len(ready_bytes) > MAX_RECORDER_READY_BYTES:
                            break
                        ready = strict_json_loads(ready_bytes.decode("utf-8"))
                    except (OSError, UnicodeError, ValueError):
                        break
                    if ready == {"port": HTTP_REQUEST_RECORDER_PORT}:
                        path = self.settings.get("path", "/")
                        return {
                            "type": self.helper.type,
                            "url": f"http://{alias}:{HTTP_REQUEST_RECORDER_PORT}{path}",
                            "authorization": f"Bearer {self.token}",
                        }
                    break
                time.sleep(0.05)
            raise VerificationInfrastructureError(
                "trusted_helper_start_failed",
                "Trusted Helper did not become ready within its bound",
                source="trusted_helper",
            )
        except BaseException:
            _remove_container(self.container_name, retry_if_absent=True)
            self.started = False
            raise

    def collect(self, catalog: TrustedHelperCatalog) -> TrustedHelperEvidence:
        if not self.started:
            raise VerificationInfrastructureError(
                "trusted_helper_runtime_invalid",
                "Trusted Helper evidence was requested before startup",
                source="trusted_helper",
            )
        _run_docker(
            ["docker", "stop", "--time", "5", self.container_name],
            "trusted_helper_crashed",
            "Trusted Helper stopped unexpectedly",
        )
        self.started = False
        records_path = self.state_dir / "requests.jsonl"
        requests: list[Any] = []
        if records_path.is_symlink():
            raise VerificationInfrastructureError(
                "trusted_helper_evidence_invalid",
                "Trusted Helper produced an invalid evidence file",
                source="trusted_helper",
            )
        if records_path.exists():
            if not records_path.is_file():
                raise VerificationInfrastructureError(
                    "trusted_helper_evidence_invalid",
                    "Trusted Helper produced an invalid evidence file",
                    source="trusted_helper",
                )
            try:
                with records_path.open("rb") as stream:
                    content = stream.read(MAX_RECORDER_EVIDENCE_BYTES + 1)
            except OSError as exc:
                raise VerificationInfrastructureError(
                    "trusted_helper_evidence_unavailable",
                    "Trusted Helper evidence could not be read",
                    source="trusted_helper",
                ) from exc
            if len(content) > MAX_RECORDER_EVIDENCE_BYTES:
                raise VerificationInfrastructureError(
                    "trusted_helper_evidence_too_large",
                    "Trusted Helper evidence exceeded its framework bound",
                    source="trusted_helper",
                )
            for line in content.splitlines():
                try:
                    requests.append(strict_json_loads(line.decode("utf-8")))
                except (UnicodeError, ValueError) as exc:
                    raise VerificationInfrastructureError(
                        "trusted_helper_evidence_invalid",
                        "Trusted Helper produced invalid evidence",
                        source="trusted_helper",
                    ) from exc
        value = {"requests": requests}
        catalog.validate_evidence(self.contract, value)
        if any(
            record["challenge_id"] != self.challenge_id
            or record["evaluation_id"] != self.evaluation_id
            for record in requests
        ):
            raise VerificationInfrastructureError(
                "trusted_helper_evidence_misbound",
                "Trusted Helper evidence belongs to another Evaluation",
                source="trusted_helper",
            )
        truncated_path = self.state_dir / "truncated.flag"
        if truncated_path.is_symlink() or (
            truncated_path.exists() and not truncated_path.is_file()
        ):
            raise VerificationInfrastructureError(
                "trusted_helper_evidence_invalid",
                "Trusted Helper produced an invalid truncation marker",
                source="trusted_helper",
            )
        _validate_recorder_records(self.helper, self.settings, requests)
        truncated = truncated_path.exists() or any(
            record["target_truncated"]
            or record["body_truncated"]
            or record["headers_truncated"]
            for record in requests
        )
        return TrustedHelperEvidence(
            name=self.helper.name,
            type=self.helper.type,
            challenge_id=self.challenge_id,
            evaluation_id=self.evaluation_id,
            value=value,
            truncated=truncated,
        )

    def close(self) -> None:
        failure: VerificationInfrastructureError | None = None
        if self.started:
            try:
                _remove_container(self.container_name)
            except VerificationInfrastructureError as exc:
                failure = exc
            self.started = False
        try:
            remove_untrusted_tree(self.root, image=HTTP_REQUEST_RECORDER_IMAGE)
        except Exception as exc:
            if failure is None:
                raise VerificationInfrastructureError(
                    "trusted_helper_cleanup_failed",
                    "Trusted Helper state cleanup failed",
                    source="trusted_helper",
                ) from exc
        if failure is not None:
            raise failure


class AppendOnlyEventLedgerRuntime:
    """One disposable timestamped event ledger for an Evaluation."""

    @staticmethod
    def validate_settings(value: Any) -> None:
        if not isinstance(value, dict):
            raise ValueError("settings must be an object")
        path = value.get("path", "/events")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or "\\" in path
            or any(character in path for character in ("?", "#", "\x00", "\r", "\n"))
            or any(ord(character) < 0x21 or ord(character) > 0x7E for character in path)
        ):
            raise ValueError("path must be one absolute HTTP origin-form path")

    def __init__(
        self,
        *,
        helper: TrustedHelperSpec,
        contract: TrustedHelperContract,
        settings: Any,
        challenge_id: str,
        evaluation_id: str,
        network: str,
    ) -> None:
        self.helper = helper
        self.contract = contract
        self.settings = settings
        self.challenge_id = challenge_id
        self.evaluation_id = evaluation_id
        self.network = network
        self.container_name = f"securebench-helper-{uuid.uuid4().hex}"
        self.root = Path(tempfile.mkdtemp(prefix="securebench-event-ledger-"))
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(mode=0o700)
        self.token = secrets.token_urlsafe(32)
        self.started = False

    def start(self, alias: str) -> dict[str, str]:
        config = {
            "challenge_id": self.challenge_id,
            "evaluation_id": self.evaluation_id,
            "settings": self.settings,
            "limits": self.helper.limits,
        }
        config_path = self.root / "config.json"
        credential_path = self.root / "credential"
        config_path.write_bytes(canonical_json_bytes(config))
        credential_path.write_text(self.token, encoding="ascii")
        config_path.chmod(0o600)
        credential_path.chmod(0o600)
        script_path = Path(__file__).with_name("event_ledger_server.py").resolve()
        command = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self.container_name,
            "--network",
            self.network,
            "--network-alias",
            alias,
            "--cap-drop",
            "ALL",
            "--cap-add",
            "DAC_OVERRIDE",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--memory",
            "128m",
            "--pids-limit",
            "64",
            "--security-opt",
            "no-new-privileges:true",
            "--label",
            "securebench.role=trusted-helper",
            "--log-driver",
            "none",
            "--mount",
            f"type=bind,source={script_path},target=/opt/securebench/ledger.py,readonly",
            "--mount",
            f"type=bind,source={config_path},target=/opt/securebench/config.json,readonly",
            "--mount",
            f"type=bind,source={credential_path},target=/opt/securebench/credential,readonly",
            "--mount",
            f"type=bind,source={self.state_dir},target=/var/lib/securebench",
            EVENT_LEDGER_IMAGE,
            "python3",
            "/opt/securebench/ledger.py",
            "--host",
            "0.0.0.0",
            "--port",
            str(EVENT_LEDGER_PORT),
            "--config",
            "/opt/securebench/config.json",
            "--credential",
            "/opt/securebench/credential",
            "--state-dir",
            "/var/lib/securebench",
        ]
        self.started = True
        try:
            _run_docker(command, "trusted_helper_start_failed", "Trusted Helper failed to start")
            deadline = time.monotonic() + HELPER_START_TIMEOUT_SECONDS
            ready_path = self.state_dir / "ready.json"
            while time.monotonic() < deadline:
                if ready_path.is_file() and not ready_path.is_symlink():
                    try:
                        with ready_path.open("rb") as stream:
                            ready_bytes = stream.read(MAX_RECORDER_READY_BYTES + 1)
                        if len(ready_bytes) > MAX_RECORDER_READY_BYTES:
                            break
                        ready = strict_json_loads(ready_bytes.decode("utf-8"))
                    except (OSError, UnicodeError, ValueError):
                        break
                    if ready == {"port": EVENT_LEDGER_PORT}:
                        path = self.settings.get("path", "/events")
                        return {
                            "type": self.helper.type,
                            "url": f"http://{alias}:{EVENT_LEDGER_PORT}{path}",
                            "authorization": f"Bearer {self.token}",
                        }
                    break
                time.sleep(0.05)
            raise VerificationInfrastructureError(
                "trusted_helper_start_failed",
                "Trusted Helper did not become ready within its bound",
                source="trusted_helper",
            )
        except BaseException:
            _remove_container(self.container_name, retry_if_absent=True)
            self.started = False
            raise

    def collect(self, catalog: TrustedHelperCatalog) -> TrustedHelperEvidence:
        if not self.started:
            raise VerificationInfrastructureError(
                "trusted_helper_runtime_invalid",
                "Trusted Helper evidence was requested before startup",
                source="trusted_helper",
            )
        _run_docker(
            ["docker", "stop", "--time", "5", self.container_name],
            "trusted_helper_crashed",
            "Trusted Helper stopped unexpectedly",
        )
        self.started = False
        events_path = self.state_dir / "events.jsonl"
        if events_path.is_symlink() or (events_path.exists() and not events_path.is_file()):
            raise VerificationInfrastructureError(
                "trusted_helper_evidence_invalid",
                "Trusted Helper produced an invalid evidence file",
                source="trusted_helper",
            )
        events: list[Any] = []
        if events_path.exists():
            try:
                with events_path.open("rb") as stream:
                    content = stream.read(MAX_EVENT_LEDGER_EVIDENCE_BYTES + 1)
            except OSError as exc:
                raise VerificationInfrastructureError(
                    "trusted_helper_evidence_unavailable",
                    "Trusted Helper evidence could not be read",
                    source="trusted_helper",
                ) from exc
            if len(content) > MAX_EVENT_LEDGER_EVIDENCE_BYTES:
                raise VerificationInfrastructureError(
                    "trusted_helper_evidence_too_large",
                    "Trusted Helper evidence exceeded its framework bound",
                    source="trusted_helper",
                )
            for line in content.splitlines():
                try:
                    events.append(strict_json_loads(line.decode("utf-8")))
                except (UnicodeError, ValueError) as exc:
                    raise VerificationInfrastructureError(
                        "trusted_helper_evidence_invalid",
                        "Trusted Helper produced invalid evidence",
                        source="trusted_helper",
                    ) from exc
        value = {"events": events}
        catalog.validate_evidence(self.contract, value)
        if any(
            event["challenge_id"] != self.challenge_id
            or event["evaluation_id"] != self.evaluation_id
            for event in events
        ):
            raise VerificationInfrastructureError(
                "trusted_helper_evidence_misbound",
                "Trusted Helper evidence belongs to another Evaluation",
                source="trusted_helper",
            )
        _validate_event_ledger_records(self.helper, self.settings, events)
        truncated_path = self.state_dir / "truncated.flag"
        if truncated_path.is_symlink() or (
            truncated_path.exists() and not truncated_path.is_file()
        ):
            raise VerificationInfrastructureError(
                "trusted_helper_evidence_invalid",
                "Trusted Helper produced an invalid truncation marker",
                source="trusted_helper",
            )
        return TrustedHelperEvidence(
            name=self.helper.name,
            type=self.helper.type,
            challenge_id=self.challenge_id,
            evaluation_id=self.evaluation_id,
            value=value,
            truncated=truncated_path.exists()
            or any(event["body_truncated"] or event["target_truncated"] for event in events),
        )

    def close(self) -> None:
        failure: VerificationInfrastructureError | None = None
        if self.started:
            try:
                _remove_container(self.container_name)
            except VerificationInfrastructureError as exc:
                failure = exc
            self.started = False
        try:
            remove_untrusted_tree(self.root, image=EVENT_LEDGER_IMAGE)
        except Exception as exc:
            if failure is None:
                raise VerificationInfrastructureError(
                    "trusted_helper_cleanup_failed",
                    "Trusted Helper state cleanup failed",
                    source="trusted_helper",
                ) from exc
        if failure is not None:
            raise failure


class ProcessSupervisorRuntime:
    """Host-only lifecycle observer and signal scheduler for one Evaluation."""

    @staticmethod
    def validate_settings(value: Any) -> None:
        if not isinstance(value, dict):
            raise ValueError("settings must be an object")
        signals = value.get("signals", [])
        if not isinstance(signals, list):
            raise ValueError("signals must be an array")
        previous = -1
        for item in signals:
            if not isinstance(item, dict) or set(item) != {"signal", "after_ms"}:
                raise ValueError("signal schedule item is invalid")
            signal_name = item["signal"]
            after_ms = item["after_ms"]
            if signal_name not in PROCESS_SUPERVISOR_SIGNALS:
                raise ValueError("signal is not in the reviewed allowlist")
            if (
                isinstance(after_ms, bool)
                or not isinstance(after_ms, int)
                or after_ms < 0
                or after_ms > MAX_PROCESS_SUPERVISOR_DELAY_MS
                or after_ms < previous
            ):
                raise ValueError("signal delay is invalid or not ordered")
            previous = after_ms

    @staticmethod
    def validate_declaration(helper: TrustedHelperSpec, settings: Any) -> None:
        signals = settings.get("signals", [])
        if len(signals) > helper.limits["max_signals"]:
            raise ValueError("signal schedule exceeds the row count bound")
        if any(item["after_ms"] > helper.limits["max_delay_ms"] for item in signals):
            raise ValueError("signal schedule exceeds the row delay bound")

    def __init__(
        self,
        *,
        helper: TrustedHelperSpec,
        contract: TrustedHelperContract,
        settings: Any,
        challenge_id: str,
        evaluation_id: str,
        network: str,
    ) -> None:
        self.helper = helper
        self.contract = contract
        self.settings = settings
        self.challenge_id = challenge_id
        self.evaluation_id = evaluation_id
        self.started = False
        self.value: dict[str, Any] | None = None

    def start(self, alias: str) -> dict[str, str]:
        if self.started or self.value is not None:
            raise VerificationInfrastructureError(
                "trusted_helper_runtime_invalid",
                "Process supervisor lifecycle is invalid",
                source="trusted_helper",
            )
        self.started = True
        return {"type": self.helper.type}

    def run_evaluation(
        self,
        sandbox: DockerSandbox,
        command: tuple[str, ...],
        *,
        workdir: str,
        timeout: float,
        stdin: bytes,
    ) -> CommandResult:
        if not self.started or self.value is not None:
            raise VerificationInfrastructureError(
                "trusted_helper_runtime_invalid",
                "Process supervisor lifecycle is invalid",
                source="trusted_helper",
            )
        signals = tuple(
            ScheduledContainerSignal(item["signal"], item["after_ms"])
            for item in self.settings.get("signals", [])
        )
        try:
            result, report = sandbox.run_supervised(
                command,
                signals=signals,
                workdir=workdir,
                timeout=timeout,
                stdin=stdin,
            )
        except DockerSandboxError as exc:
            raise VerificationInfrastructureError(
                "trusted_helper_supervision_failed",
                "Process supervisor could not control the Evaluation process",
                source="trusted_helper",
            ) from exc
        self.value = {
            "process": {
                "container_started": report.container_started,
                "started_after_ms": report.started_after_ms,
                "duration_ms": report.duration_ms,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
            },
            "signals": [
                {
                    "sequence": item.sequence,
                    "signal": item.signal,
                    "scheduled_after_ms": item.scheduled_after_ms,
                    "attempted_after_ms": item.attempted_after_ms,
                    "delivered": item.delivered,
                }
                for item in report.signals
            ],
        }
        return result

    def collect(self, catalog: TrustedHelperCatalog) -> TrustedHelperEvidence:
        if not self.started:
            raise VerificationInfrastructureError(
                "trusted_helper_runtime_invalid",
                "Process supervisor evidence was requested before startup",
                source="trusted_helper",
            )
        if self.value is None:
            raise VerificationInfrastructureError(
                "trusted_helper_runtime_invalid",
                "Process supervisor evidence was requested before execution",
                source="trusted_helper",
            )
        catalog.validate_evidence(self.contract, self.value)
        _validate_process_supervisor_evidence(self.helper, self.settings, self.value)
        return TrustedHelperEvidence(
            name=self.helper.name,
            type=self.helper.type,
            challenge_id=self.challenge_id,
            evaluation_id=self.evaluation_id,
            value=self.value,
            truncated=False,
        )

    def close(self) -> None:
        self.started = False


class TrustedHelperEvaluation:
    """Own the internal network and all helper instances for one Evaluation."""

    def __init__(
        self,
        *,
        task: BenchmarkTask,
        check: ProtocolCheck,
        catalog: TrustedHelperCatalog,
        challenge_id: str,
        evaluation_id: str,
    ) -> None:
        self.task = task
        self.check = check
        self.catalog = catalog
        self.challenge_id = challenge_id
        self.evaluation_id = evaluation_id
        self.network = "none"
        self._network_name: str | None = None
        self._runtimes: list[Any] = []

    def start(self) -> dict[str, dict[str, str]]:
        if not self.check.trusted_helpers:
            return {}
        access: dict[str, dict[str, str]] = {}
        try:
            contracts = [
                self.catalog.validate_declaration(helper)
                for helper in self.check.trusted_helpers
            ]
            if any(contract.helper_access == "http" for contract in contracts):
                self._network_name = f"securebench-evaluation-{uuid.uuid4().hex}"
                _run_docker(
                    [
                        "docker",
                        "network",
                        "create",
                        *ISOLATED_BRIDGE_ARGUMENTS,
                        "--label",
                        "securebench.role=trusted-helper-network",
                        self._network_name,
                    ],
                    "trusted_helper_network_failed",
                    "Trusted Helper Evaluation network could not be created",
                )
                try:
                    validate_private_network(
                        self._network_name,
                        lambda command: _run_docker(
                            command, "trusted_helper_network_failed",
                            "Trusted Helper network could not be inspected",
                        ),
                    )
                except ConfigError as exc:
                    raise VerificationInfrastructureError(
                        "trusted_helper_network_failed", str(exc), source="trusted_helper",
                    ) from exc
                self.network = self._network_name
            for index, helper in enumerate(self.check.trusted_helpers):
                contract = contracts[index]
                settings = load_trusted_helper_settings(self.task, helper.settings)
                self.catalog.validate_settings(contract, settings)
                self.catalog.validate_runtime_settings(helper.type, settings)
                self.catalog.validate_runtime_declaration(helper, settings)
                factory = self.catalog.runtime_factory(helper.type)
                runtime = factory(
                    helper=helper,
                    contract=contract,
                    settings=settings,
                    challenge_id=self.challenge_id,
                    evaluation_id=self.evaluation_id,
                    network=self.network,
                )
                self._runtimes.append(runtime)
                access[helper.name] = runtime.start(f"securebench-helper-{index}")
        except BaseException:
            self.close()
            raise
        return access

    def evaluation_environment(self) -> dict[str, str]:
        """Disable inherited proxies while retaining direct helper name resolution."""
        if self._network_name is None:
            return {}
        no_proxy = ",".join(
            ["localhost", "127.0.0.1", "::1"]
            + [f"securebench-helper-{index}" for index in range(len(self.check.trusted_helpers))]
        )
        return {
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
            "NO_PROXY": no_proxy,
            "http_proxy": "",
            "https_proxy": "",
            "all_proxy": "",
            "no_proxy": no_proxy,
        }

    def run_evaluation(
        self,
        sandbox: DockerSandbox,
        command: tuple[str, ...],
        *,
        workdir: str,
        timeout: float,
        stdin: bytes,
    ) -> CommandResult:
        """Run through the optional single host-only process supervisor."""
        supervisors = [
            runtime
            for runtime in self._runtimes
            if callable(getattr(runtime, "run_evaluation", None))
        ]
        if len(supervisors) > 1:
            raise VerificationInfrastructureError(
                "trusted_helper_contract_invalid",
                "At most one process-control Trusted Helper may own Evaluation launch",
                source="trusted_helper",
            )
        if supervisors:
            return supervisors[0].run_evaluation(
                sandbox,
                command,
                workdir=workdir,
                timeout=timeout,
                stdin=stdin,
            )
        return sandbox.run(
            command,
            workdir=workdir,
            timeout=timeout,
            stdin=stdin,
        )

    def collect(self) -> tuple[TrustedHelperEvidence, ...]:
        return tuple(runtime.collect(self.catalog) for runtime in self._runtimes)

    def close(self) -> None:
        failures: list[VerificationInfrastructureError] = []
        for runtime in reversed(self._runtimes):
            try:
                runtime.close()
            except VerificationInfrastructureError as exc:
                failures.append(exc)
        self._runtimes.clear()
        if self._network_name is not None:
            try:
                _remove_network(self._network_name)
            except VerificationInfrastructureError as exc:
                failures.append(exc)
            else:
                self._network_name = None
                self.network = "none"
        if failures:
            raise failures[0]


def _run_docker(command: list[str], code: str, message: str) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=DOCKER_OPERATION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerificationInfrastructureError(code, message, source="trusted_helper") from exc
    if completed.returncode != 0:
        if code == "trusted_helper_network_failed":
            message += ": " + completed.stderr.strip()[:2048]
        raise VerificationInfrastructureError(code, message, source="trusted_helper")

    return completed.stdout


def _validate_recorder_records(
    helper: TrustedHelperSpec,
    settings: Any,
    requests: list[Any],
) -> None:
    """Independently enforce row-reduced bounds and record semantics on host."""
    max_requests = helper.limits["max_requests"]
    max_body_bytes = helper.limits["max_body_bytes"]
    max_header_bytes = helper.limits.get("max_header_bytes", MAX_RECORDER_HEADER_BYTES)
    if len(requests) > max_requests:
        _invalid_recorder_evidence("Trusted Helper returned too many request records")
    expected_path = settings.get("path", "/")
    for index, record in enumerate(requests):
        if record["sequence"] != index:
            _invalid_recorder_evidence("Trusted Helper request sequence is invalid")
        if record["method"] not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            _invalid_recorder_evidence("Trusted Helper request method is invalid")
        try:
            body = base64.b64decode(record["body_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise VerificationInfrastructureError(
                "trusted_helper_evidence_invalid",
                "Trusted Helper request body encoding is invalid",
                source="trusted_helper",
            ) from exc
        if (
            len(body) != record["body_bytes"]
            or len(body) > max_body_bytes
            or record["declared_body_bytes"] < len(body)
            or record["body_sha256"]
            != "sha256:" + hashlib.sha256(body).hexdigest()
        ):
            _invalid_recorder_evidence("Trusted Helper request body metadata is invalid")
        if not record["body_truncated"] and record["declared_body_bytes"] != len(body):
            _invalid_recorder_evidence("Trusted Helper request body length is inconsistent")
        retained_header_bytes = sum(
            len(header["name"].encode("utf-8"))
            + len(header["value"].encode("utf-8"))
            + 4
            for header in record["headers"]
        )
        if (
            retained_header_bytes > max_header_bytes
            or record["header_bytes"] < retained_header_bytes
            or any(
                header["name"] != header["name"].lower()
                or header["name"] in {"authorization", "proxy-authorization"}
                or RECORDED_HEADER_NAME.fullmatch(header["name"]) is None
                or any(
                    (ord(character) < 0x20 and character != "\t")
                    or ord(character) == 0x7F
                    for character in header["value"]
                )
                for header in record["headers"]
            )
        ):
            _invalid_recorder_evidence("Trusted Helper request header metadata is invalid")
        target = record["target"]
        try:
            request_path = urlsplit(target).path
        except ValueError:
            request_path = ""
        expected_match = (
            target.startswith("/")
            and not target.startswith("//")
            and "\\" not in target
            and "#" not in target
            and all(0x21 <= ord(character) <= 0x7E for character in target)
            and request_path == expected_path
        )
        if record["path_matched"] != expected_match:
            _invalid_recorder_evidence("Trusted Helper request path metadata is invalid")
        target_invalid = (
            "\\" in target
            or "#" in target
            or any(ord(character) < 0x21 or ord(character) > 0x7E for character in target)
        )
        if record["target_truncated"]:
            expected_statuses = {414}
        elif target_invalid:
            expected_statuses = {400}
        elif record["headers_truncated"] or record["header_bytes"] > max_header_bytes:
            expected_statuses = {431}
        elif record["body_truncated"]:
            # The recorder uses 400 for ambiguous framing and 413 for an
            # oversized or incomplete fixed-length body. Evidence deliberately
            # excludes the untrusted framing headers themselves.
            expected_statuses = {400, 413}
        elif not record["authenticated"]:
            expected_statuses = {401}
        elif not record["path_matched"]:
            expected_statuses = {404}
        else:
            expected_statuses = {settings.get("response_status", 204)}
        if record["response_status"] not in expected_statuses:
            _invalid_recorder_evidence("Trusted Helper response status metadata is invalid")


def _validate_event_ledger_records(
    helper: TrustedHelperSpec,
    settings: Any,
    events: list[Any],
) -> None:
    """Independently enforce event-ledger bounds and response semantics."""
    maximum_events = helper.limits["max_events"]
    maximum_body = helper.limits["max_event_bytes"]
    if len(events) > maximum_events:
        _invalid_event_ledger_evidence("Trusted Helper returned too many event records")
    previous_elapsed = -1
    expected_path = settings.get("path", "/events")
    for index, event in enumerate(events):
        if event["sequence"] != index:
            _invalid_event_ledger_evidence("Trusted Helper event sequence is invalid")
        elapsed = event["elapsed_us"]
        if elapsed < 0 or elapsed < previous_elapsed:
            _invalid_event_ledger_evidence("Trusted Helper event timing is not monotonic")
        previous_elapsed = elapsed
        if event["method"] not in {
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "HEAD",
            "OPTIONS",
        }:
            _invalid_event_ledger_evidence("Trusted Helper event method is invalid")
        if (
            event["body_bytes"] < 0
            or event["body_bytes"] > maximum_body
            or event["declared_body_bytes"] < event["body_bytes"]
            or event["header_bytes"] < 0
        ):
            _invalid_event_ledger_evidence("Trusted Helper event size metadata is invalid")
        if not event["body_truncated"] and event["declared_body_bytes"] != event["body_bytes"]:
            _invalid_event_ledger_evidence("Trusted Helper event body length is inconsistent")
        try:
            body = base64.b64decode(event["body_base64"], validate=True)
        except (TypeError, ValueError) as exc:
            raise VerificationInfrastructureError(
                "trusted_helper_evidence_invalid",
                "Trusted Helper event body encoding is invalid",
                source="trusted_helper",
            ) from exc
        if (
            len(body) != event["body_bytes"]
            or event["body_sha256"]
            != "sha256:" + hashlib.sha256(body).hexdigest()
        ):
            _invalid_event_ledger_evidence("Trusted Helper event digest is invalid")

        target = event["target"]
        try:
            request_path = urlsplit(target).path
        except ValueError:
            request_path = ""
        target_valid = (
            not event["target_truncated"]
            and target.startswith("/")
            and not target.startswith("//")
            and "\\" not in target
            and "#" not in target
            and all(0x21 <= ord(character) <= 0x7E for character in target)
        )
        if event["path_matched"] != (target_valid and request_path == expected_path):
            _invalid_event_ledger_evidence("Trusted Helper event path metadata is invalid")

        fields_valid = (
            EVENT_LEDGER_NONCE.fullmatch(event["nonce"]) is not None
            and EVENT_LEDGER_EVENT_NAME.fullmatch(event["event"]) is not None
            and len(event["data"].encode("utf-8")) <= maximum_body
        )
        if event["event_valid"] != fields_valid:
            _invalid_event_ledger_evidence("Trusted Helper event field metadata is invalid")
        if event["body_truncated"] and event["event_valid"]:
            _invalid_event_ledger_evidence("Truncated event body was marked valid")
        if not event["event_valid"] and any(
            event[name] for name in ("nonce", "event", "data")
        ):
            _invalid_event_ledger_evidence("Invalid event retained parsed fields")
        if event["event_valid"]:
            try:
                parsed = strict_json_loads(body.decode("utf-8"))
            except (UnicodeError, ValueError) as exc:
                raise VerificationInfrastructureError(
                    "trusted_helper_evidence_invalid",
                    "Trusted Helper retained an invalid accepted event body",
                    source="trusted_helper",
                ) from exc
            if parsed != {
                "nonce": event["nonce"],
                "event": event["event"],
                "data": event["data"],
            }:
                _invalid_event_ledger_evidence(
                    "Trusted Helper event fields do not match the recorded body"
                )

        if event["target_truncated"]:
            statuses = {414}
        elif not target_valid:
            statuses = {400}
        elif event["method"] != "POST":
            statuses = {405}
        elif not event["path_matched"]:
            statuses = {404}
        elif event["header_bytes"] > 16 * 1024:
            statuses = {431}
        elif event["body_truncated"]:
            statuses = {400, 413}
        elif not event["authenticated"]:
            statuses = {401}
        elif not event["content_type_valid"] or not event["event_valid"]:
            statuses = {400}
        else:
            statuses = {202}
        if event["response_status"] not in statuses:
            _invalid_event_ledger_evidence("Trusted Helper event response metadata is invalid")
        if event["accepted"] != (event["response_status"] == 202):
            _invalid_event_ledger_evidence("Trusted Helper event acceptance metadata is invalid")


def _validate_process_supervisor_evidence(
    helper: TrustedHelperSpec,
    settings: Any,
    value: dict[str, Any],
) -> None:
    """Independently enforce the configured process-supervision schedule."""
    configured = settings.get("signals", [])
    observed = value["signals"]
    process = value["process"]
    if len(observed) != len(configured) or len(observed) > helper.limits["max_signals"]:
        _invalid_process_supervisor_evidence("Process supervisor signal count is invalid")
    if process["duration_ms"] < 0:
        _invalid_process_supervisor_evidence("Process supervisor duration is invalid")
    if process["container_started"] != (process["started_after_ms"] >= 0):
        _invalid_process_supervisor_evidence("Process supervisor startup metadata is invalid")
    if not process["container_started"] and any(
        item["attempted_after_ms"] != -1 for item in observed
    ):
        _invalid_process_supervisor_evidence("A signal was attempted before container startup")
    for index, (expected, actual) in enumerate(zip(configured, observed, strict=True)):
        if (
            actual["sequence"] != index
            or actual["signal"] != expected["signal"]
            or actual["scheduled_after_ms"] != expected["after_ms"]
            or actual["scheduled_after_ms"] > helper.limits["max_delay_ms"]
        ):
            _invalid_process_supervisor_evidence("Process supervisor schedule metadata is invalid")
        attempted = actual["attempted_after_ms"]
        if attempted < -1:
            _invalid_process_supervisor_evidence("Signal attempt timing is invalid")
        if attempted >= 0 and attempted < actual["scheduled_after_ms"]:
            _invalid_process_supervisor_evidence("Signal attempt predates its schedule")
        if attempted > process["duration_ms"]:
            _invalid_process_supervisor_evidence("Signal attempt exceeds process duration")
        if actual["delivered"] and attempted == -1:
            _invalid_process_supervisor_evidence("Delivered signal has no attempt timing")


def _invalid_event_ledger_evidence(message: str) -> None:
    raise VerificationInfrastructureError(
        "trusted_helper_evidence_invalid",
        message,
        source="trusted_helper",
    )


def _invalid_process_supervisor_evidence(message: str) -> None:
    raise VerificationInfrastructureError(
        "trusted_helper_evidence_invalid",
        message,
        source="trusted_helper",
    )


def _invalid_recorder_evidence(message: str) -> None:
    raise VerificationInfrastructureError(
        "trusted_helper_evidence_invalid",
        message,
        source="trusted_helper",
    )


def _remove_container(name: str, *, retry_if_absent: bool = False) -> None:
    attempts = INTERRUPTED_HELPER_CLEANUP_ATTEMPTS if retry_if_absent else 1
    for attempt in range(attempts):
        try:
            completed = subprocess.run(
                ["docker", "rm", "-f", name],
                check=False,
                capture_output=True,
                text=True,
                timeout=DOCKER_OPERATION_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise VerificationInfrastructureError(
                "trusted_helper_cleanup_failed",
                "Trusted Helper container cleanup failed",
                source="trusted_helper",
            ) from exc
        if completed.returncode == 0:
            return
        if "no such container" not in completed.stderr.lower():
            raise VerificationInfrastructureError(
                "trusted_helper_cleanup_failed",
                "Trusted Helper container cleanup failed",
                source="trusted_helper",
            )
        if attempt + 1 < attempts:
            # An interrupted `docker run` can return before the daemon has
            # published the named container. Keep cleanup ownership briefly
            # so a late-created helper cannot escape teardown.
            time.sleep(INTERRUPTED_HELPER_CLEANUP_INTERVAL_SECONDS)


def _remove_network(name: str) -> None:
    try:
        completed = subprocess.run(
            ["docker", "network", "rm", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=DOCKER_OPERATION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerificationInfrastructureError(
            "trusted_helper_cleanup_failed",
            "Trusted Helper Evaluation network cleanup failed",
            source="trusted_helper",
        ) from exc
    if completed.returncode != 0 and "not found" not in completed.stderr.lower():
        raise VerificationInfrastructureError(
            "trusted_helper_cleanup_failed",
            "Trusted Helper Evaluation network cleanup failed",
            source="trusted_helper",
        )
