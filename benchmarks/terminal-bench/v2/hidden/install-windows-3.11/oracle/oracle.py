"""Host-only Oracle for the Windows 3.11 QEMU conversion."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import PurePosixPath
import sys
from typing import Any


CHECK_ID = "windows_runtime_behavior"
SUPERVISOR_TYPE = "securebench.process-supervisor/v1"
DISK_SHA256 = "58fb76014dccf13ec048e894ca1e44773eee940ccbc71c97a2ab3d07285da553"
DISK_SIZE = 268_435_456
KEYS = ("f1", "alt-tab", "f10", "alt-f4", "ctrl-esc")
MAX_DECODED_BYTES = 16_384


def build_cases(run_seed: str) -> list[dict[str, Any]]:
    digest = hashlib.sha256(("install-windows-3.11\0" + run_seed).encode()).digest()
    ordered = sorted(KEYS, key=lambda key: hashlib.sha256(digest + key.encode()).digest())
    return [
        {
            "challenge": {"keys": ordered},
            "context": {
                "keys": ordered,
                "disk_sha256": DISK_SHA256,
                "disk_size": DISK_SIZE,
                "minimum_change_numerator": 1,
                "minimum_change_denominator": 10,
            },
        }
    ]


def _decode(value: Any) -> bytes:
    if not isinstance(value, str):
        raise ValueError("encoded observation must be text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("encoded observation is malformed") from error
    if len(decoded) > MAX_DECODED_BYTES:
        raise ValueError("encoded observation exceeds limit")
    return decoded


def _valid_qemu_process(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"pid", "executable", "arguments"}:
        return False
    arguments = value.get("arguments")
    executable = value.get("executable")
    if (
        isinstance(value.get("pid"), bool)
        or not isinstance(value.get("pid"), int)
        or value["pid"] <= 0
        or not isinstance(executable, str)
        or not isinstance(arguments, list)
        or not arguments
        or any(not isinstance(argument, str) for argument in arguments)
    ):
        return False
    binary = PurePosixPath(arguments[0]).name
    if binary not in {"qemu-system-i386", "qemu-system-x86_64"}:
        return False
    joined = "\0".join(arguments)
    paired = set(zip(arguments, arguments[1:]))
    return all(
        (
            "-snapshot" in arguments or "snapshot=on" in joined,
            "/app/isos/win311.img" in joined,
            any(left == "-vga" and right for left, right in paired),
            any(left == "-m" and right for left, right in paired),
            ("-vnc", ":1") in paired,
            "unix:/tmp/qemu-monitor.sock" in joined,
        )
    )


class WindowsQemuOracle:
    def __init__(self) -> None:
        self.cases: list[dict[str, Any]] = []
        self.case_index = 0
        self.evaluated = 0
        self.evaluation_ids: set[str] = set()
        self.failures: list[str] = []

    def initialize(self, run_seed: str) -> None:
        self.cases = build_cases(run_seed)

    def next_case(self) -> dict[str, Any]:
        if self.case_index >= len(self.cases):
            return {"type": "exhausted"}
        case = self.cases[self.case_index]
        self.case_index += 1
        return {
            "type": "case",
            "challenge": case["challenge"],
            "case_context": case["context"],
        }

    def fail(self, category: str) -> None:
        self.failures.append(category)

    def _helper_valid(self, evidence: dict[str, Any]) -> bool:
        helpers = evidence.get("trusted_helper_evidence")
        challenge = evidence.get("challenge")
        if not isinstance(helpers, dict) or not isinstance(challenge, dict):
            return False
        helper = helpers.get("process_control")
        if (
            not isinstance(helper, dict)
            or helper.get("type") != SUPERVISOR_TYPE
            or helper.get("challenge_id") != challenge.get("id")
            or helper.get("evaluation_id") != evidence.get("evaluation_id")
            or helper.get("truncated") is not False
        ):
            return False
        value = helper.get("value")
        if not isinstance(value, dict) or value.get("signals") != []:
            return False
        process = value.get("process")
        return (
            isinstance(process, dict)
            and process.get("container_started") is True
            and process.get("exit_code") == 0
            and process.get("timed_out") is False
            and isinstance(process.get("duration_ms"), int)
            and process["duration_ms"] > 0
        )

    def evaluate_case(self, context: dict[str, Any], evidence: dict[str, Any]) -> None:
        self.evaluated += 1
        if evidence.get("status") != "observed":
            failure = evidence.get("failure")
            code = failure.get("code") if isinstance(failure, dict) else None
            self.fail(str(code or "runtime_execution_failed"))
            return
        evaluation_id = evidence.get("evaluation_id")
        if not isinstance(evaluation_id, str) or evaluation_id in self.evaluation_ids:
            self.fail("evaluation_not_fresh")
        else:
            self.evaluation_ids.add(evaluation_id)
        if not self._helper_valid(evidence):
            self.fail("host_lifecycle_invalid")

        observation = evidence.get("observation")
        if not isinstance(observation, dict):
            self.fail("invalid_observation")
            return
        try:
            _decode(observation.get("stdout_base64"))
            _decode(observation.get("stderr_base64"))
            monitor = _decode(observation.get("monitor_base64"))
        except ValueError:
            self.fail("invalid_observation")
            return
        if (
            observation.get("launcher_exit") != 0
            or observation.get("launcher_timed_out") is not False
            or observation.get("output_too_large") is not False
        ):
            self.fail("launcher_failed")

        processes = observation.get("qemu_processes")
        if not isinstance(processes, list) or len(processes) != 1 or not _valid_qemu_process(processes[0]):
            self.fail("qemu_configuration_invalid")
        ports = observation.get("listen_ports")
        if not isinstance(ports, list) or not {80, 5_901}.issubset(set(ports)):
            self.fail("required_service_unavailable")
        if (
            observation.get("disk_sha256_before") != context.get("disk_sha256")
            or observation.get("disk_sha256_after") != context.get("disk_sha256")
            or observation.get("disk_size_before") != context.get("disk_size")
            or observation.get("disk_size_after") != context.get("disk_size")
        ):
            self.fail("disk_identity_or_immutability_invalid")

        http = observation.get("http")
        if (
            not isinstance(http, dict)
            or http.get("status") != 200
            or http.get("body_too_large") is not False
            or http.get("error") != ""
        ):
            self.fail("web_interface_invalid")
        else:
            try:
                body = _decode(http.get("body_base64"))
            except ValueError:
                self.fail("web_interface_invalid")
            else:
                if not body:
                    self.fail("web_interface_invalid")
        if observation.get("monitor_error") != "" or not monitor:
            self.fail("monitor_control_invalid")

        baseline = observation.get("baseline")
        if (
            not isinstance(baseline, dict)
            or baseline.get("capture_error") != ""
            or not isinstance(baseline.get("width"), int)
            or not isinstance(baseline.get("height"), int)
            or baseline["width"] <= 0
            or baseline["height"] <= 0
            or not isinstance(baseline.get("sha256"), str)
            or len(baseline["sha256"]) != 64
        ):
            self.fail("baseline_frame_invalid")

        frames = observation.get("frames")
        keys = context.get("keys")
        if not isinstance(frames, list) or not isinstance(keys, list) or len(frames) != len(keys):
            self.fail("frame_sequence_invalid")
            return
        changed_enough = False
        for key, frame in zip(keys, frames):
            if not isinstance(frame, dict) or frame.get("key") != key:
                self.fail("frame_sequence_invalid")
                continue
            try:
                monitor_reply = _decode(frame.get("monitor_base64"))
            except ValueError:
                self.fail("keyboard_control_invalid")
                continue
            different = frame.get("different_components")
            total = frame.get("total_components")
            if (
                frame.get("monitor_error") != ""
                or frame.get("capture_error") != ""
                or not monitor_reply
                or isinstance(different, bool)
                or not isinstance(different, int)
                or isinstance(total, bool)
                or not isinstance(total, int)
                or different < 0
                or total <= 0
                or different > total
            ):
                self.fail("keyboard_control_invalid")
                continue
            if (
                different * int(context["minimum_change_denominator"])
                >= total * int(context["minimum_change_numerator"])
            ):
                changed_enough = True
        if not changed_enough:
            self.fail("keyboard_visual_feedback_missing")

    def verdict(self) -> dict[str, Any]:
        behavior = (
            len(self.cases) == 1
            and self.evaluated == 1
            and len(self.evaluation_ids) == 1
            and not self.failures
        )
        return {
            "type": "verdict",
            "verdict": {
                "passed": behavior,
                "score": 1.0 if behavior else 0.0,
                "check_outcomes": {CHECK_ID: behavior},
                "public_diagnostics": {
                    "message": (
                        "Windows/QEMU runtime satisfied the bounded scenario"
                        if behavior
                        else "Windows/QEMU runtime did not satisfy the task"
                    ),
                    "failure_categories": sorted(set(self.failures))[:20],
                },
            },
        }


def main() -> None:
    oracle = WindowsQemuOracle()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation == "initialize":
                run_seed = request.get("run_seed")
                if not isinstance(run_seed, str):
                    raise ValueError("run seed is required")
                oracle.initialize(run_seed)
                response = {"type": "ack"}
            elif operation == "next_case":
                if (
                    request.get("check_id") != CHECK_ID
                    or request.get("challenge_source") != "host.task_oracle"
                    or request.get("bounds") != {"max_cases": 1, "max_case_bytes": 4_096}
                ):
                    raise ValueError("unsupported check")
                response = oracle.next_case()
            elif operation == "evaluate_case":
                if request.get("check_id") != CHECK_ID:
                    raise ValueError("unsupported check")
                context = request.get("case_context")
                evidence = request.get("evidence")
                if not isinstance(context, dict) or not isinstance(evidence, dict):
                    raise ValueError("case evaluation is invalid")
                oracle.evaluate_case(context, evidence)
                response = {"type": "ack"}
            elif operation == "finalize":
                response = oracle.verdict()
            else:
                raise ValueError("unsupported operation")
        except Exception:
            response = {"type": "error"}
        print(json.dumps(response, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
