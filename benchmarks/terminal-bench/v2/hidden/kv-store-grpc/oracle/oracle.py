"""Host-only Oracle for the restartable KVStore gRPC conversion."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import random
import re
import string
import sys
from typing import Any

from securebench.verification.json_data import json_digest


ARTIFACT_CHECK = "kv_store_artifacts"
BEHAVIOR_CHECK = "kv_store_behavior"
ARTIFACT_IDS = {"proto", "python_bindings", "grpc_bindings", "server"}
MAX_CASES = 3
MAX_CASE_BYTES = 16_384
MAX_DECODED_BYTES = 32_768


def _without_comments(text: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", " ", text, flags=re.DOTALL)


def _block(text: str, kind: str, name: str) -> str | None:
    text = _without_comments(text)
    match = re.search(
        rf"\b{re.escape(kind)}\s+{re.escape(name)}\s*\{{",
        text,
    )
    if match is None:
        return None
    start = match.end()
    depth = 1
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index]
    return None


def proto_matches_contract(text: str) -> bool:
    service = _block(text, "service", "KVStore")
    get_request = _block(text, "message", "GetValRequest")
    get_response = _block(text, "message", "GetValResponse")
    set_request = _block(text, "message", "SetValRequest")
    set_response = _block(text, "message", "SetValResponse")
    if None in {service, get_request, get_response, set_request, set_response}:
        return False
    assert service is not None
    assert get_request is not None
    assert get_response is not None
    assert set_request is not None
    assert set_response is not None
    return all(
        (
            re.search(
                r"\brpc\s+GetVal\s*\(\s*GetValRequest\s*\)\s*returns\s*"
                r"\(\s*GetValResponse\s*\)",
                service,
            ),
            re.search(
                r"\brpc\s+SetVal\s*\(\s*SetValRequest\s*\)\s*returns\s*"
                r"\(\s*SetValResponse\s*\)",
                service,
            ),
            re.search(r"\bstring\s+key\s*=\s*1\s*;", get_request),
            re.search(r"\bint32\s+val\s*=\s*1\s*;", get_response),
            re.search(r"\bstring\s+key\s*=\s*1\s*;", set_request),
            re.search(r"\bint32\s+value\s*=\s*2\s*;", set_request),
            re.search(r"\bint32\s+val\s*=\s*1\s*;", set_response),
        )
    )


def _case(case_id: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, int] = {}
    expected = []
    for operation in operations:
        if operation["rpc"] == "set":
            values[operation["key"]] = operation["value"]
            expected.append(operation["value"])
        else:
            expected.append(values.get(operation["key"], 0))
    challenge = {"operations": operations}
    return {
        "id": case_id,
        "challenge": challenge,
        "context": {
            "case_id": case_id,
            "expected": expected,
            "challenge_digest": json_digest(challenge),
        },
    }


def build_cases(run_seed: str) -> list[dict[str, Any]]:
    seed = hashlib.sha256(("kv-store-grpc\0" + run_seed).encode()).digest()
    generator = random.Random(seed)

    def key(label: str) -> str:
        suffix = "".join(generator.choice(string.ascii_letters) for _ in range(12))
        return f"{label}-{suffix}"

    first = key("source")
    first_value = generator.randrange(1, 1_000_000)
    updated_value = generator.randrange(1, 1_000_000)
    if updated_value == first_value:
        updated_value += 1
    left, right = key("left"), key("right")
    left_value = -generator.randrange(1, 1_000_000)
    right_value = generator.randrange(1, 1_000_000)
    unicode_key = f"unicode-κλειδί-{generator.randrange(10_000, 99_999)}"
    unicode_value = -generator.randrange(1, 1_000_000)

    return [
        _case(
            "set_get_update",
            [
                {"rpc": "set", "key": first, "value": first_value},
                {"rpc": "get", "key": first},
                {"rpc": "set", "key": first, "value": updated_value},
                {"rpc": "get", "key": first},
            ],
        ),
        _case(
            "independent_keys",
            [
                {"rpc": "set", "key": left, "value": left_value},
                {"rpc": "set", "key": right, "value": right_value},
                {"rpc": "get", "key": left},
                {"rpc": "get", "key": right},
                {"rpc": "set", "key": left, "value": 0},
                {"rpc": "get", "key": left},
                {"rpc": "get", "key": right},
            ],
        ),
        _case(
            "utf8_key_and_negative_value",
            [
                {"rpc": "set", "key": unicode_key, "value": unicode_value},
                {"rpc": "get", "key": unicode_key},
            ],
        ),
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


class KvStoreOracle:
    def __init__(self) -> None:
        self.cases: list[dict[str, Any]] = []
        self.case_index = 0
        self.evaluated = 0
        self.evaluation_ids: set[str] = set()
        self.artifact_outcomes: dict[str, bool] = {}
        self.artifacts_valid = True
        self.behavior_passed = True
        self.failures: list[str] = []

    def initialize(self, run_seed: str) -> None:
        self.cases = build_cases(run_seed)
        self.case_index = 0
        self.evaluated = 0
        self.evaluation_ids.clear()
        self.artifact_outcomes.clear()
        self.artifacts_valid = True
        self.behavior_passed = True
        self.failures.clear()

    def evaluate_artifact(self, evidence: dict[str, Any]) -> None:
        artifact_id = evidence.get("artifact_id")
        if evidence.get("check_id") != ARTIFACT_CHECK or artifact_id not in ARTIFACT_IDS:
            self.artifacts_valid = False
            self.failures.append("uncorrelated_artifact")
            return
        if not isinstance(artifact_id, str) or artifact_id in self.artifact_outcomes:
            self.artifacts_valid = False
            self.failures.append("duplicate_artifact")
            return
        value = evidence.get("parsed_value")
        passed = evidence.get("status") == "observed" and isinstance(value, str)
        if passed and artifact_id == "proto":
            passed = proto_matches_contract(value)
        elif passed and artifact_id in {"python_bindings", "grpc_bindings"}:
            passed = bool(value.strip())
        elif passed and artifact_id == "server":
            passed = re.search(r"\bclass\s+Server\b", value) is not None
        self.artifact_outcomes[artifact_id] = passed
        if not passed:
            self.failures.append(f"invalid_{artifact_id}")

    def next_case(self) -> dict[str, Any]:
        if self.case_index >= len(self.cases):
            return {"type": "exhausted"}
        case = self.cases[self.case_index]
        context = dict(case["context"])
        context["case_index"] = self.case_index
        self.case_index += 1
        return {
            "type": "case",
            "challenge": case["challenge"],
            "case_context": context,
        }

    def _fail_behavior(self, category: str) -> None:
        self.behavior_passed = False
        self.failures.append(category)

    def evaluate_case(self, context: dict[str, Any], evidence: dict[str, Any]) -> None:
        self.evaluated += 1
        case_index = context.get("case_index")
        if evidence.get("check_id") != BEHAVIOR_CHECK:
            self._fail_behavior("check_correlation_failed")
            return
        if (
            type(case_index) is not int
            or not 0 <= case_index < len(self.cases)
            or self.cases[case_index]["id"] != context.get("case_id")
        ):
            self._fail_behavior("case_context_invalid")
            return
        challenge = evidence.get("challenge")
        if (
            not isinstance(challenge, dict)
            or challenge.get("index") != case_index
            or challenge.get("digest") != context.get("challenge_digest")
        ):
            self._fail_behavior("challenge_correlation_failed")
            return
        if evidence.get("status") != "observed":
            failure = evidence.get("failure")
            code = failure.get("code") if isinstance(failure, dict) else None
            self._fail_behavior(str(code or "service_execution_failed"))
            return
        evaluation_id = evidence.get("evaluation_id")
        if not isinstance(evaluation_id, str) or evaluation_id in self.evaluation_ids:
            self._fail_behavior("evaluation_not_fresh")
            return
        self.evaluation_ids.add(evaluation_id)
        observation = evidence.get("observation")
        if not isinstance(observation, dict):
            self._fail_behavior("invalid_observation")
            return
        try:
            _decode(observation.get("stdout_base64"))
            _decode(observation.get("stderr_base64"))
        except ValueError:
            self._fail_behavior("invalid_observation")
            return
        if (
            observation.get("server_started") is not True
            or observation.get("process_running") is not True
            or observation.get("process_exit") != -1
            or observation.get("output_too_large") is not False
        ):
            self._fail_behavior("service_not_running")
        expected = context.get("expected")
        responses = observation.get("responses")
        if not isinstance(expected, list) or not isinstance(responses, list):
            self._fail_behavior("invalid_observation")
            return
        if len(responses) != len(expected):
            self._fail_behavior("incorrect_response_count")
            return
        for expected_value, response in zip(expected, responses):
            if (
                not isinstance(response, dict)
                or response.get("status") != "returned"
                or response.get("error") != ""
                or type(response.get("val")) is not int
                or response["val"] != expected_value
            ):
                self._fail_behavior("incorrect_rpc_response")

    def verdict(self) -> dict[str, Any]:
        artifacts = (
            self.artifacts_valid
            and set(self.artifact_outcomes) == ARTIFACT_IDS
            and all(self.artifact_outcomes.values())
        )
        behavior = (
            self.evaluated == len(self.cases)
            and len(self.evaluation_ids) == len(self.cases)
            and self.behavior_passed
        )
        passed = artifacts and behavior
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {
                    ARTIFACT_CHECK: artifacts,
                    BEHAVIOR_CHECK: behavior,
                },
                "public_diagnostics": {
                    "message": (
                        "KVStore artifacts and gRPC behavior are correct"
                        if passed
                        else "KVStore artifacts or gRPC behavior did not satisfy the task"
                    ),
                    "failure_categories": sorted(set(self.failures))[:20],
                },
            },
        }


def main() -> None:
    oracle = KvStoreOracle()
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
                    != {"max_cases": MAX_CASES, "max_case_bytes": MAX_CASE_BYTES}
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
