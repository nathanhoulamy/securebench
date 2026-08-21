"""Reviewed Trusted Helper catalog and per-Evaluation runtime lifecycle."""

from __future__ import annotations

import base64
import hashlib
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
HTTP_REQUEST_RECORDER_IMAGE = (
    "python:3.11-slim@sha256:"
    "9c900dea9e8fb7e16277c179b555cc72d29a352dbc33cff48ad5a0412fd5bfc7"
)
HTTP_REQUEST_RECORDER_PORT = 8080
MAX_TRUSTED_HELPER_SETTINGS_BYTES = 256 * 1024
MAX_RECORDER_RECORDS = 128
MAX_RECORDER_BODY_BYTES = 65536
MAX_RECORDER_HEADER_BYTES = 32768
MAX_RECORDER_RESPONSE_BYTES = 16384
MAX_RECORDER_EVIDENCE_BYTES = 20 * 1024 * 1024
HELPER_START_TIMEOUT_SECONDS = 10.0
DOCKER_OPERATION_TIMEOUT_SECONDS = 30.0


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


def default_trusted_helper_catalog() -> TrustedHelperCatalog:
    """Return the framework-owned catalog of implemented, reviewed helpers."""
    contract = http_request_recorder_contract()
    return TrustedHelperCatalog(
        (contract,),
        runtime_factories={HTTP_REQUEST_RECORDER_TYPE: HttpRequestRecorderRuntime},
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
        if status in {204, 304} and value.get("response_body", ""):
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
        _run_docker(command, "trusted_helper_start_failed", "Trusted Helper failed to start")
        self.started = True
        deadline = time.monotonic() + HELPER_START_TIMEOUT_SECONDS
        ready_path = self.state_dir / "ready.json"
        while time.monotonic() < deadline:
            if ready_path.is_file() and not ready_path.is_symlink():
                try:
                    ready = strict_json_loads(ready_path.read_text(encoding="utf-8"))
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
            record["body_truncated"] or record["headers_truncated"]
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
        self._network_name = f"securebench-evaluation-{uuid.uuid4().hex}"
        _run_docker(
            ["docker", "network", "create", "--internal", self._network_name],
            "trusted_helper_network_failed",
            "Trusted Helper Evaluation network could not be created",
        )
        self.network = self._network_name
        access: dict[str, dict[str, str]] = {}
        try:
            for index, helper in enumerate(self.check.trusted_helpers):
                contract = self.catalog.validate_declaration(helper)
                settings = load_trusted_helper_settings(self.task, helper.settings)
                self.catalog.validate_settings(contract, settings)
                self.catalog.validate_runtime_settings(helper.type, settings)
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
        except Exception:
            self.close()
            raise
        return access

    def evaluation_environment(self) -> dict[str, str]:
        """Disable inherited proxies while retaining direct helper name resolution."""
        if not self.check.trusted_helpers:
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
            self._network_name = None
            self.network = "none"
        if failures:
            raise failures[0]


def _run_docker(command: list[str], code: str, message: str) -> None:
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
        raise VerificationInfrastructureError(code, message, source="trusted_helper")


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
                header["name"] in {"authorization", "proxy-authorization"}
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
            and request_path == expected_path
        )
        if record["path_matched"] != expected_match:
            _invalid_recorder_evidence("Trusted Helper request path metadata is invalid")
        if not 200 <= record["response_status"] <= 599:
            _invalid_recorder_evidence("Trusted Helper response status is invalid")


def _invalid_recorder_evidence(message: str) -> None:
    raise VerificationInfrastructureError(
        "trusted_helper_evidence_invalid",
        message,
        source="trusted_helper",
    )


def _remove_container(name: str) -> None:
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
    if completed.returncode != 0 and "No such container" not in completed.stderr:
        raise VerificationInfrastructureError(
            "trusted_helper_cleanup_failed",
            "Trusted Helper container cleanup failed",
            source="trusted_helper",
        )


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
