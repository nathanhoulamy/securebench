"""Host-only Oracle ABI and bounded subprocess transport."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

from securebench.tasks import BenchmarkTask
from securebench.verification.models import (
    ArtifactEvidence,
    OracleVerdict,
    VerificationInfrastructureError,
)


ORACLE_ABI = "securebench.oracle/v1"
MAX_ORACLE_RESPONSE_BYTES = 1024 * 1024


class OracleSession(ABC):
    """Stateful host-only Oracle lifecycle."""

    @abstractmethod
    def initialize(self, task: BenchmarkTask, *, run_seed: str) -> None:
        ...

    @abstractmethod
    def evaluate_artifact(self, evidence: ArtifactEvidence) -> None:
        ...

    def next_case(self, check_id: str, challenge_source: str, bounds: dict[str, Any]) -> Any:
        raise NotImplementedError

    def evaluate_case(self, check_id: str, case_context: Any, evidence: dict[str, Any]) -> None:
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
        manifest_path = self.resource_root / "oracle.yaml"
        try:
            manifest = yaml.safe_load(manifest_path.read_text())
        except OSError as exc:
            raise VerificationInfrastructureError(
                "oracle_manifest_missing", "Oracle manifest is unavailable"
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
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise VerificationInfrastructureError(
                "oracle_manifest_invalid", "Oracle command is invalid"
            )
        timeout = manifest.get("timeout_seconds")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise VerificationInfrastructureError(
                "oracle_manifest_invalid", "Oracle timeout is invalid"
            )
        self.timeout_seconds = float(timeout)
        resolved_command = [sys.executable if part == "{python}" else part for part in command]
        self.process = subprocess.Popen(
            resolved_command,
            cwd=self.resource_root,
            env=_oracle_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
        )

    def initialize(self, task: BenchmarkTask, *, run_seed: str) -> None:
        resources = {
            resource.name: resource.value
            for resource in task.view_for("oracle").resources
            if resource.kind in {"file", "directory"}
        }
        self._request(
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

    def evaluate_artifact(self, evidence: ArtifactEvidence) -> None:
        self._request(
            {"op": "evaluate_artifact", "evidence": evidence.internal_record()},
            expected="ack",
        )

    def finalize(self) -> OracleVerdict:
        response = self._request({"op": "finalize"}, expected="verdict")
        verdict = response.get("verdict")
        if not isinstance(verdict, dict):
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle returned an invalid verdict"
            )
        try:
            return OracleVerdict(
                passed=verdict["passed"],
                score=verdict["score"],
                public_diagnostics=verdict.get("public_diagnostics", {}),
                check_outcomes=verdict.get("check_outcomes", {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle returned an invalid verdict"
            ) from exc

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)

    def _request(self, request: dict[str, Any], *, expected: str) -> dict[str, Any]:
        if self.process.poll() is not None:
            raise VerificationInfrastructureError(
                "oracle_exited", "Oracle process exited unexpectedly"
            )
        assert self.process.stdin is not None
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            self.process.stdin.write(encoded)
            self.process.stdin.flush()
        except OSError as exc:
            raise VerificationInfrastructureError(
                "oracle_io_error", "Failed to send evidence to Oracle"
            ) from exc
        response = self._read_response()
        if response.get("type") == "error":
            raise VerificationInfrastructureError(
                "oracle_reported_error", "Oracle reported an internal error"
            )
        if response.get("type") != expected:
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle returned an unexpected response"
            )
        return response

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
            response = json.loads(bytes(content[:newline]))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle response was not valid JSON"
            ) from exc
        if not isinstance(response, dict):
            raise VerificationInfrastructureError(
                "oracle_protocol_error", "Oracle response must be an object"
            )
        return response


def _oracle_environment() -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }
    for name in ("LANG", "LC_ALL", "TMPDIR"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment
