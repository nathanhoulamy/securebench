"""Host-only Oracle ABI and bounded subprocess transport."""

from __future__ import annotations

import math
import os
import selectors
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from securebench.tasks import BenchmarkTask
from securebench.verification.json_data import canonical_json_bytes, strict_json_loads
from securebench.verification.models import (
    ArtifactEvidence,
    OracleCase,
    OracleVerdict,
    ProtocolCaseEvidence,
    VerificationInfrastructureError,
)


ORACLE_ABI = "securebench.oracle/v1"
MAX_ORACLE_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ORACLE_COMMAND_PARTS = 32
MAX_ORACLE_COMMAND_PART_BYTES = 4096


@dataclass(frozen=True)
class OracleManifest:
    command: tuple[str, ...]
    timeout_seconds: float


class OracleSession(ABC):
    """Stateful host-only Oracle lifecycle."""

    @abstractmethod
    def initialize(self, task: BenchmarkTask, *, run_seed: str) -> None:
        ...

    @abstractmethod
    def evaluate_artifact(self, evidence: ArtifactEvidence) -> None:
        ...

    def next_case(
        self,
        check_id: str,
        challenge_source: str,
        bounds: dict[str, Any],
    ) -> OracleCase | None:
        raise NotImplementedError

    def evaluate_case(
        self,
        check_id: str,
        case_context: Any,
        evidence: ProtocolCaseEvidence,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def finalize(self) -> OracleVerdict:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    def __enter__(self) -> "OracleSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class OracleProcessSession(OracleSession):
    """Run a reviewed pack-local Oracle over bounded JSON-lines messages."""

    def __init__(self, resource_root: str | Path) -> None:
        self.resource_root = Path(resource_root).resolve()
        manifest = load_oracle_manifest(self.resource_root)
        self.timeout_seconds = manifest.timeout_seconds
        resolved_command = [
            sys.executable if part == "{python}" else part for part in manifest.command
        ]
        try:
            self.process = subprocess.Popen(
                resolved_command,
                cwd=self.resource_root,
                env=_oracle_environment(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                # Oracle diagnostics are trusted-host details and are never public.
                # Discarding them also prevents an undrained stderr pipe from
                # deadlocking the bounded request/response channel.
                stderr=subprocess.DEVNULL,
                text=False,
                bufsize=0,
            )
        except (OSError, ValueError) as exc:
            raise VerificationInfrastructureError(
                "oracle_start_failed", "Oracle process could not be started"
            ) from exc
        assert self.process.stdin is not None
        try:
            os.set_blocking(self.process.stdin.fileno(), False)
        except OSError as exc:
            self.close()
            raise VerificationInfrastructureError(
                "oracle_start_failed", "Oracle process channel could not be initialized"
            ) from exc

    def initialize(self, task: BenchmarkTask, *, run_seed: str) -> None:
        resources = {
            resource.name: resource.value
            for resource in task.view_for("oracle").resources
            if resource.kind in {"file", "directory"}
        }
        response = self._request(
            {
                "op": "initialize",
                "row": {
                    "id": task.id,
                    "benchmark_id": task.benchmark_id,
                    "family": task.family,
                    "row_digest": task.row_digest,
                },
                "run_seed": run_seed,
                "resources": resources,
            },
            expected="ack",
        )
        _require_ack(response)

    def evaluate_artifact(self, evidence: ArtifactEvidence) -> None:
        response = self._request(
            {"op": "evaluate_artifact", "evidence": evidence.internal_record()},
            expected="ack",
        )
        _require_ack(response)

    def next_case(
        self,
        check_id: str,
        challenge_source: str,
        bounds: dict[str, Any],
    ) -> OracleCase | None:
        response = self._request(
            {
                "op": "next_case",
                "check_id": check_id,
                "challenge_source": challenge_source,
                "bounds": bounds,
            },
            expected=("case", "exhausted"),
        )
        if response["type"] == "exhausted":
            if set(response) != {"type"}:
                raise VerificationInfrastructureError(
                    "oracle_protocol_error", "Oracle returned an invalid exhausted response"
                )
            return None
        if set(response) != {"type", "challenge", "case_context"}:
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle returned an invalid case response"
            )
        try:
            case = OracleCase(
                challenge=response["challenge"],
                context=response["case_context"],
            )
            maximum = bounds["max_case_bytes"]
            if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
                raise ValueError("invalid case bound")
            challenge_bytes = canonical_json_bytes(case.challenge)
        except (KeyError, TypeError, ValueError) as exc:
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle returned an invalid case response"
            ) from exc
        if len(challenge_bytes) > maximum:
            raise VerificationInfrastructureError(
                "oracle_case_too_large", "Oracle challenge exceeded its declared bound"
            )
        return case

    def evaluate_case(
        self,
        check_id: str,
        case_context: Any,
        evidence: ProtocolCaseEvidence,
    ) -> None:
        response = self._request(
            {
                "op": "evaluate_case",
                "check_id": check_id,
                "case_context": case_context,
                "evidence": evidence.internal_record(),
            },
            expected="ack",
        )
        _require_ack(response)

    def finalize(self) -> OracleVerdict:
        response = self._request({"op": "finalize"}, expected="verdict")
        if set(response) != {"type", "verdict"}:
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle returned an invalid verdict response"
            )
        verdict = response.get("verdict")
        if not isinstance(verdict, dict):
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle returned an invalid verdict"
            )
        required_fields = {"passed", "score", "check_outcomes"}
        allowed_fields = {*required_fields, "public_diagnostics"}
        if not required_fields.issubset(verdict) or not set(verdict).issubset(allowed_fields):
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle returned an invalid verdict"
            )
        try:
            return OracleVerdict(
                passed=verdict["passed"],
                score=verdict["score"],
                public_diagnostics=verdict.get("public_diagnostics", {}),
                check_outcomes=verdict["check_outcomes"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle returned an invalid verdict"
            ) from exc

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        self.process.kill()
                        self.process.wait(timeout=1)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
        finally:
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def _request(
        self,
        request: dict[str, Any],
        *,
        expected: str | tuple[str, ...],
    ) -> dict[str, Any]:
        if self.process.poll() is not None:
            raise VerificationInfrastructureError(
                "oracle_exited", "Oracle process exited unexpectedly"
            )
        assert self.process.stdin is not None
        try:
            encoded = canonical_json_bytes(request) + b"\n"
        except (TypeError, ValueError) as exc:
            raise VerificationInfrastructureError(
                "oracle_request_invalid", "Oracle request was not finite JSON data"
            ) from exc
        self._write_request(encoded)
        response = self._read_response()
        if response.get("type") == "error":
            raise VerificationInfrastructureError(
                "oracle_reported_error", "Oracle reported an internal error"
            )
        expected_types = (expected,) if isinstance(expected, str) else expected
        if response.get("type") not in expected_types:
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle returned an unexpected response"
            )
        return response

    def _write_request(self, encoded: bytes) -> None:
        assert self.process.stdin is not None
        selector = selectors.DefaultSelector()
        selector.register(self.process.stdin, selectors.EVENT_WRITE)
        deadline = time.monotonic() + self.timeout_seconds
        offset = 0
        try:
            while offset < len(encoded):
                if self.process.poll() is not None:
                    raise VerificationInfrastructureError(
                        "oracle_exited", "Oracle process exited unexpectedly"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise VerificationInfrastructureError(
                        "oracle_timeout", "Oracle exceeded its request timeout"
                    )
                if not selector.select(remaining):
                    continue
                try:
                    written = os.write(
                        self.process.stdin.fileno(),
                        encoded[offset : offset + 64 * 1024],
                    )
                except BlockingIOError:
                    continue
                except OSError as exc:
                    raise VerificationInfrastructureError(
                        "oracle_io_error", "Failed to send evidence to Oracle"
                    ) from exc
                if written <= 0:
                    raise VerificationInfrastructureError(
                        "oracle_io_error", "Failed to send evidence to Oracle"
                    )
                offset += written
        finally:
            selector.close()

    def _read_response(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(self.process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + self.timeout_seconds
        content = bytearray()
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise VerificationInfrastructureError(
                        "oracle_timeout", "Oracle exceeded its response timeout"
                    )
                events = selector.select(remaining)
                if not events:
                    continue
                chunk = os.read(self.process.stdout.fileno(), 4096)
                if not chunk:
                    raise VerificationInfrastructureError(
                        "oracle_exited", "Oracle process exited without a response"
                    )
                content.extend(chunk)
                if len(content) > MAX_ORACLE_RESPONSE_BYTES:
                    raise VerificationInfrastructureError(
                        "oracle_response_too_large", "Oracle response exceeded its bound"
                    )
                newline = content.find(b"\n")
                if newline >= 0:
                    if content[newline + 1 :]:
                        raise VerificationInfrastructureError(
                            "oracle_protocol_error", "Oracle emitted unsolicited output"
                        )
                    break
        finally:
            selector.close()
        try:
            response = strict_json_loads(bytes(content[:newline]))
        except (UnicodeDecodeError, ValueError) as exc:
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle response was not valid JSON"
            ) from exc
        if not isinstance(response, dict):
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle response must be an object"
            )
        return response


def oracle_resource_root(task: BenchmarkTask) -> Path:
    """Resolve the host-only Oracle directory declared by a compiled task."""
    _, identifier = task.verification.oracle.split(".", 1)
    resource = task.resources.resources.get(f"host.{identifier}")
    if resource is None:
        raise VerificationInfrastructureError(
            "oracle_resource_missing", "Oracle host resource is unavailable"
        )
    if resource.kind != "directory" or not isinstance(resource.value, dict):
        raise VerificationInfrastructureError(
            "oracle_resource_invalid", "Oracle host resource is invalid"
        )
    source_path = resource.value.get("source_path")
    if not isinstance(source_path, str):
        raise VerificationInfrastructureError(
            "oracle_resource_invalid", "Oracle host resource is invalid"
        )
    source = Path(source_path)
    if not source.is_absolute() or not source.is_dir() or source.is_symlink():
        raise VerificationInfrastructureError(
            "oracle_resource_invalid", "Oracle host resource is invalid"
        )
    return source


def load_oracle_manifest(resource_root: str | Path) -> OracleManifest:
    """Validate a trusted pack-local Oracle manifest without starting it."""
    manifest_path = Path(resource_root).resolve() / "oracle.yaml"
    try:
        manifest_text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VerificationInfrastructureError(
            "oracle_manifest_missing", "Oracle manifest is unavailable"
        ) from exc
    except UnicodeError as exc:
        raise VerificationInfrastructureError(
            "oracle_manifest_invalid", "Oracle manifest is not valid UTF-8"
        ) from exc
    try:
        manifest = yaml.safe_load(manifest_text)
    except yaml.YAMLError as exc:
        raise VerificationInfrastructureError(
            "oracle_manifest_invalid", "Oracle manifest is not valid YAML"
        ) from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "abi",
        "command",
        "timeout_seconds",
    }:
        raise VerificationInfrastructureError(
            "oracle_manifest_invalid", "Oracle manifest has an invalid shape"
        )
    if manifest.get("abi") != ORACLE_ABI:
        raise VerificationInfrastructureError(
            "oracle_abi_unsupported", "Oracle ABI is unsupported"
        )
    command = manifest.get("command")
    if (
        not isinstance(command, list)
        or not command
        or len(command) > MAX_ORACLE_COMMAND_PARTS
        or not all(
            isinstance(part, str)
            and bool(part)
            and "\x00" not in part
            and len(part.encode("utf-8")) <= MAX_ORACLE_COMMAND_PART_BYTES
            for part in command
        )
        or not command[0].strip()
    ):
        raise VerificationInfrastructureError(
            "oracle_manifest_invalid", "Oracle command is invalid"
        )
    timeout = manifest.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise VerificationInfrastructureError(
            "oracle_manifest_invalid", "Oracle timeout is invalid"
        )
    try:
        timeout_seconds = float(timeout)
    except OverflowError as exc:
        raise VerificationInfrastructureError(
            "oracle_manifest_invalid", "Oracle timeout is invalid"
        ) from exc
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise VerificationInfrastructureError(
            "oracle_manifest_invalid", "Oracle timeout is invalid"
        )
    return OracleManifest(command=tuple(command), timeout_seconds=timeout_seconds)


def _oracle_environment() -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    for name in ("LANG", "LC_ALL", "TMPDIR"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _require_ack(response: dict[str, Any]) -> None:
    if set(response) != {"type"}:
        raise VerificationInfrastructureError(
            "oracle_protocol_error", "Oracle returned an invalid acknowledgement"
        )
