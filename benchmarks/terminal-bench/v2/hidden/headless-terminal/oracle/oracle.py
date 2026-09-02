"""Host-only Oracle for bounded headless-terminal interaction scenarios."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sys
from typing import Any


CHECK_ID = "terminal_behavior"
MAX_OBSERVED_BYTES = 4_096
BASE64_OBSERVATIONS = (
    "driver_stdout_base64",
    "driver_stderr_base64",
    "file_base64",
    "http_body_base64",
)


def _encoded(value: str | bytes) -> str:
    content = value.encode() if isinstance(value, str) else value
    return base64.b64encode(content).decode("ascii")


def _step(keys: str, wait_ms: int = 0) -> dict[str, Any]:
    return {"keys_base64": _encoded(keys), "wait_ms": wait_ms}


def _case(
    *,
    steps: list[dict[str, Any]],
    file_name: str,
    expected_file: str | None,
    startup: str = "",
    server_body: str = "",
    http_port: int = 0,
    expected_http: str | None = None,
) -> dict[str, Any]:
    return {
        "challenge": {
            "startup_base64": _encoded(startup),
            "server_body_base64": _encoded(server_body),
            "steps": steps,
            "file_path": f"observed/{file_name}",
            "http_port": http_port,
            "http_path": "/",
        },
        "context": {
            "expected_file": expected_file,
            "expected_http": expected_http,
        },
    }


def build_cases(run_seed: str) -> list[dict[str, Any]]:
    values = [
        "securebench_"
        + hashlib.sha256(
            f"headless-terminal\0{run_seed}\0{index}".encode()
        ).hexdigest()[:16]
        for index in range(6)
    ]
    observed = "/app/.securebench-case/observed"
    server = "/app/.securebench-case/server"
    return [
        _case(
            steps=[
                _step(f"printf '%s' '{values[0]}' > {observed}/noninteractive"),
                _step("\n", 700),
            ],
            file_name="noninteractive",
            expected_file=values[0],
        ),
        _case(
            steps=[
                _step(f"export SECUREBENCH_FILE={observed}/persistent"),
                _step("\n", 300),
                _step(f"printf '%s' '{values[1]}' > \"$SECUREBENCH_FILE\""),
                _step("\n", 700),
            ],
            file_name="persistent",
            expected_file=values[1],
        ),
        _case(
            steps=[
                _step("python -q"),
                _step("\n", 500),
                _step(
                    f"open('{observed}/interactive','w').write('{values[2]}')"
                ),
                _step("\n", 500),
                _step("\x04", 300),
            ],
            file_name="interactive",
            expected_file=values[2],
        ),
        _case(
            steps=[
                _step(
                    f"sleep 2 && printf '%s' '{values[3]}' > {observed}/cancelled"
                ),
                _step("\n", 400),
                _step("\x03", 500),
                _step("", 1_700),
            ],
            file_name="cancelled",
            expected_file=None,
        ),
        _case(
            startup=f"export SECUREBENCH_STARTUP_VALUE={values[4]}\n",
            steps=[
                _step(
                    f"printf '%s' \"$SECUREBENCH_STARTUP_VALUE\" > {observed}/startup"
                ),
                _step("\n", 700),
            ],
            file_name="startup",
            expected_file=values[4],
        ),
        _case(
            server_body=values[5],
            steps=[
                _step(
                    "python -m http.server 18080 --bind 127.0.0.1 "
                    f"--directory {server} &"
                ),
                _step("\n", 1_200),
            ],
            file_name="background-unused",
            expected_file=None,
            http_port=18_080,
            expected_http=values[5],
        ),
    ]


def _decode(value: Any) -> bytes:
    if not isinstance(value, str):
        raise ValueError("encoded observation must be text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("encoded observation is malformed") from error
    if len(decoded) > MAX_OBSERVED_BYTES * 2:
        raise ValueError("decoded observation exceeds limit")
    return decoded


class HeadlessTerminalOracle:
    def __init__(self) -> None:
        self.cases: list[dict[str, Any]] = []
        self.case_index = 0
        self.evaluated = 0
        self.passed = True
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

    def evaluate_case(self, context: dict[str, Any], evidence: dict[str, Any]) -> None:
        self.evaluated += 1
        if evidence.get("status") != "observed":
            self.passed = False
            failure = evidence.get("failure")
            code = failure.get("code") if isinstance(failure, dict) else None
            self.failures.append(str(code or "terminal_execution_failed"))
            return
        evaluation_id = evidence.get("evaluation_id")
        if not isinstance(evaluation_id, str) or evaluation_id in self.evaluation_ids:
            self.passed = False
            self.failures.append("evaluation_not_fresh")
        else:
            self.evaluation_ids.add(evaluation_id)
        observation = evidence.get("observation")
        if not isinstance(observation, dict):
            self.passed = False
            self.failures.append("invalid_observation")
            return
        try:
            decoded = {
                field: _decode(observation.get(field)) for field in BASE64_OBSERVATIONS
            }
        except ValueError:
            self.passed = False
            self.failures.append("invalid_observation")
            return
        if observation.get("driver_exit") != 0:
            self.passed = False
            self.failures.append("terminal_execution_failed")
            return

        expected_file = context.get("expected_file")
        should_exist = isinstance(expected_file, str)
        if (
            observation.get("file_exists") is not should_exist
            or observation.get("file_too_large") is not False
        ):
            self.passed = False
            self.failures.append("incorrect_file_effect")
        elif should_exist:
            try:
                actual = decoded["file_base64"].decode("utf-8", errors="strict").strip()
            except UnicodeDecodeError:
                actual = ""
            if actual != expected_file:
                self.passed = False
                self.failures.append("incorrect_file_effect")

        expected_http = context.get("expected_http")
        if isinstance(expected_http, str):
            try:
                body = decoded["http_body_base64"].decode("utf-8", errors="strict").strip()
            except UnicodeDecodeError:
                body = ""
            if (
                observation.get("http_attempted") is not True
                or observation.get("http_status") != 200
                or observation.get("http_too_large") is not False
                or observation.get("http_error") != ""
                or body != expected_http
            ):
                self.passed = False
                self.failures.append("incorrect_background_service")
        elif observation.get("http_attempted") is not False:
            self.passed = False
            self.failures.append("unexpected_http_observation")

    def verdict(self) -> dict[str, Any]:
        behavior = (
            len(self.cases) == 6
            and self.evaluated == len(self.cases)
            and len(self.evaluation_ids) == len(self.cases)
            and self.passed
        )
        return {
            "type": "verdict",
            "verdict": {
                "passed": behavior,
                "score": 1.0 if behavior else 0.0,
                "check_outcomes": {CHECK_ID: behavior},
                "public_diagnostics": {
                    "message": (
                        "Headless terminal behavior satisfied the bounded scenarios"
                        if behavior
                        else "Headless terminal behavior did not satisfy the task"
                    ),
                    "failure_categories": sorted(set(self.failures))[:20],
                },
            },
        }


def main() -> None:
    oracle = HeadlessTerminalOracle()
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
                    or request.get("bounds")
                    != {"max_cases": 6, "max_case_bytes": 65_536}
                ):
                    raise ValueError("unsupported check")
                response = oracle.next_case()
            elif operation == "evaluate_case":
                context = request.get("case_context")
                evidence = request.get("evidence")
                if (
                    request.get("check_id") != CHECK_ID
                    or not isinstance(context, dict)
                    or not isinstance(evidence, dict)
                ):
                    raise ValueError("case evidence is required")
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
