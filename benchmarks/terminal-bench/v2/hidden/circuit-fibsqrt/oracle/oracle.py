"""Host-only Oracle for circuit-fibsqrt artifact shape and circuit behavior."""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from typing import Any


SHAPE_CHECK = "circuit_shape"
BEHAVIOR_CHECK = "circuit_behavior"
MAX_LINES = 31_999
ORIGINAL_CASES = (
    1,
    4,
    8,
    12,
    41,
    42,
    107,
    220,
    209,
    366,
    12**2,
    41**2,
    42**2,
    107**2,
    220**2,
    209**2,
    12**2 - 1,
    41**2 - 1,
    42**2 - 1,
    107**2 - 1,
    220**2 - 1,
    209**2 - 1,
    12**2 + 1,
    41**2 + 1,
    42**2 + 1,
    107**2 + 1,
    220**2 + 1,
    209**2 + 1,
)


def physical_line_count(text: str) -> int:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.count("\n") + int(bool(normalized) and not normalized.endswith("\n"))


def fibonacci_mod_32(index: int) -> int:
    """Return Fibonacci(index) modulo 2^32 using fast doubling."""

    def pair(value: int) -> tuple[int, int]:
        if value == 0:
            return (0, 1)
        first, second = pair(value >> 1)
        doubled = (first * ((2 * second - first) & 0xFFFF_FFFF)) & 0xFFFF_FFFF
        adjacent = (first * first + second * second) & 0xFFFF_FFFF
        if value & 1:
            return (adjacent, (doubled + adjacent) & 0xFFFF_FFFF)
        return (doubled, adjacent)

    return pair(index)[0]


def expected_output(input_value: int) -> int:
    return fibonacci_mod_32(math.isqrt(input_value))


class CircuitOracle:
    def __init__(self) -> None:
        self.cases: list[int] = []
        self.case_index = 0
        self.shape_evaluated = False
        self.shape_passed = False
        self.behavior_evaluated = 0
        self.behavior_passed = True
        self.evaluation_ids: set[str] = set()
        self.failures: list[str] = []

    def initialize(self, run_seed: str) -> None:
        seed = hashlib.sha256(("circuit-fibsqrt\0" + run_seed).encode("utf-8")).digest()
        generator = random.Random(seed)
        used = set(ORIGINAL_CASES)
        while True:
            root = generator.randrange(2, 221)
            boundary = (root * root - 1, root * root, root * root + 1)
            if used.isdisjoint(boundary):
                break
        used.update(boundary)
        while True:
            general = generator.randrange(1, 220**2 + 2)
            if general not in used:
                break
        hidden = (general, *boundary)
        self.cases = [*ORIGINAL_CASES, *hidden]

    def evaluate_artifact(self, evidence: dict[str, Any]) -> None:
        if evidence.get("check_id") != SHAPE_CHECK:
            self.failures.append("unexpected_artifact")
            return
        self.shape_evaluated = True
        if evidence.get("status") != "observed":
            error = evidence.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            self.failures.append(str(code or "artifact_rejected"))
            return
        value = evidence.get("parsed_value")
        if not isinstance(value, str):
            self.failures.append("invalid_circuit_text")
            return
        if "\x00" in value:
            self.failures.append("invalid_gate_text")
            return
        self.shape_passed = physical_line_count(value) <= MAX_LINES
        if not self.shape_passed:
            self.failures.append("too_many_gates")

    def next_case(self) -> dict[str, Any]:
        if self.case_index >= len(self.cases):
            return {"type": "exhausted"}
        input_value = self.cases[self.case_index]
        context = {"expected": expected_output(input_value)}
        self.case_index += 1
        return {
            "type": "case",
            "challenge": {"input": input_value},
            "case_context": context,
        }

    def evaluate_case(self, context: dict[str, Any], evidence: dict[str, Any]) -> None:
        self.behavior_evaluated += 1
        if evidence.get("status") != "observed":
            self.behavior_passed = False
            failure = evidence.get("failure")
            code = failure.get("code") if isinstance(failure, dict) else None
            self.failures.append(str(code or "circuit_execution_failed"))
            return
        evaluation_id = evidence.get("evaluation_id")
        if not isinstance(evaluation_id, str) or evaluation_id in self.evaluation_ids:
            self.behavior_passed = False
            self.failures.append("evaluation_not_fresh")
        else:
            self.evaluation_ids.add(evaluation_id)
        observation = evidence.get("observation")
        if not isinstance(observation, dict) or observation.get("exit_code") != 0:
            self.behavior_passed = False
            self.failures.append("circuit_execution_failed")
            return
        stdout = observation.get("stdout")
        if not isinstance(stdout, str):
            self.behavior_passed = False
            self.failures.append("invalid_output")
            return
        try:
            actual = int(stdout.strip())
        except ValueError:
            self.behavior_passed = False
            self.failures.append("invalid_output")
            return
        if actual != context.get("expected"):
            self.behavior_passed = False
            self.failures.append("incorrect_output")

    def verdict(self) -> dict[str, Any]:
        shape = self.shape_evaluated and self.shape_passed
        behavior = (
            self.behavior_evaluated == len(self.cases)
            and len(self.evaluation_ids) == len(self.cases)
            and self.behavior_passed
        )
        passed = shape and behavior
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {SHAPE_CHECK: shape, BEHAVIOR_CHECK: behavior},
                "public_diagnostics": {
                    "message": (
                        "Circuit matched the bounded Fibonacci-square-root challenge suite"
                        if passed
                        else "Circuit artifact or behavior did not satisfy the task"
                    ),
                    "failure_categories": sorted(set(self.failures))[:20],
                },
            },
        }


def main() -> None:
    oracle = CircuitOracle()
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
            elif operation == "evaluate_artifact":
                evidence = request.get("evidence")
                if not isinstance(evidence, dict):
                    raise ValueError("artifact evidence is required")
                oracle.evaluate_artifact(evidence)
                response = {"type": "ack"}
            elif operation == "next_case":
                if (
                    request.get("check_id") != BEHAVIOR_CHECK
                    or request.get("challenge_source") != "host.task_oracle"
                    or request.get("bounds")
                    != {"max_cases": 32, "max_case_bytes": 128}
                ):
                    raise ValueError("unsupported check")
                response = oracle.next_case()
            elif operation == "evaluate_case":
                context = request.get("case_context")
                evidence = request.get("evidence")
                if (
                    request.get("check_id") != BEHAVIOR_CHECK
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
