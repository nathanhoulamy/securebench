"""Host-only Oracle for bounded GPT-2 compilation and continuation behavior."""

from __future__ import annotations

import base64
import binascii
import json
import sys
from typing import Any


CHECK_ID = "gpt2_continuation_behavior"
CASES = (
    (
        'THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT',
        "WARRANTY OF ANY KIND, EXPRESS OR IMPLIED",
    ),
    (
        "The meaning of life is",
        " not a matter of the individual, but of the collective.",
    ),
)
BASE64_FIELDS = (
    "compile_stdout_base64",
    "compile_stderr_base64",
    "stdout_base64",
    "stderr_base64",
)


def _decode_bounded(value: Any, *, maximum: int = 65_536) -> bytes:
    if not isinstance(value, str):
        raise ValueError("encoded observation must be a string")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("invalid observation encoding") from error
    if len(decoded) > maximum:
        raise ValueError("decoded observation exceeds limit")
    return decoded


class Gpt2CodegolfOracle:
    def __init__(self) -> None:
        self.case_index = 0
        self.evaluated = 0
        self.passed = True
        self.evaluation_ids: set[str] = set()
        self.failures: list[str] = []

    def next_case(self) -> dict[str, Any]:
        if self.case_index >= len(CASES):
            return {"type": "exhausted"}
        prompt, expected = CASES[self.case_index]
        self.case_index += 1
        return {
            "type": "case",
            "challenge": {
                "prompt_base64": base64.b64encode(prompt.encode()).decode("ascii")
            },
            "case_context": {"expected": expected},
        }

    def evaluate_case(self, context: dict[str, Any], evidence: dict[str, Any]) -> None:
        self.evaluated += 1
        if evidence.get("status") != "observed":
            self.passed = False
            failure = evidence.get("failure")
            code = failure.get("code") if isinstance(failure, dict) else None
            self.failures.append(str(code or "evaluation_failed"))
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
            outputs = {field: _decode_bounded(observation.get(field)) for field in BASE64_FIELDS}
        except ValueError:
            self.passed = False
            self.failures.append("invalid_observation")
            return
        if observation.get("compile_exit") != 0:
            self.passed = False
            self.failures.append("compilation_failed")
            return
        if observation.get("run_exit") != 0:
            self.passed = False
            self.failures.append("execution_failed")
            return
        try:
            stdout = outputs["stdout_base64"].decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            self.passed = False
            self.failures.append("invalid_output")
            return
        expected = context.get("expected")
        if not isinstance(expected, str) or expected not in stdout:
            self.passed = False
            self.failures.append("incorrect_output")

    def verdict(self) -> dict[str, Any]:
        behavior = (
            self.evaluated == len(CASES)
            and len(self.evaluation_ids) == len(CASES)
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
                        "The bounded GPT-2 continuation checks passed"
                        if behavior
                        else "The GPT-2 implementation did not satisfy the task"
                    ),
                    "failure_categories": sorted(set(self.failures))[:20],
                },
            },
        }


def main() -> None:
    oracle = Gpt2CodegolfOracle()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation == "initialize":
                if not isinstance(request.get("run_seed"), str):
                    raise ValueError("run seed is required")
                response = {"type": "ack"}
            elif operation == "next_case":
                if (
                    request.get("check_id") != CHECK_ID
                    or request.get("challenge_source") != "host.task_oracle"
                    or request.get("bounds")
                    != {"max_cases": 2, "max_case_bytes": 8192}
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
