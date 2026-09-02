"""Host-only Oracle for the restartable sentiment service conversion."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import sys
from typing import Any


CHECK_ID = "sentiment_service_behavior"
MAX_DECODED_BYTES = 32_768
SOURCE_TEXTS = (
    ("I really enjoyed this movie, it was amazing!", "positive"),
    ("The service at this restaurant was terrible and the food was cold.", "negative"),
    ("This movie was not good at all; in fact, it was quite boring.", "negative"),
    ("I am not happy with the customer service I received.", "negative"),
    ("The journey was not bad; I actually had a good time.", "positive"),
    ("The view from the top of the mountain was horribly beautiful.", "positive"),
)
POSITIVE_TEXTS = (
    "A delightful and thoughtful performance.",
    "This product is superb and exceeded every expectation.",
    "What a fantastic, joyful, and beautifully made film.",
    "The experience was wonderful from beginning to end.",
)
NEGATIVE_TEXTS = (
    "This was a disappointing waste of time.",
    "The broken product was frustrating and completely useless.",
    "What an awful, tedious, and unpleasant experience.",
    "The performance was dreadful from beginning to end.",
)


def _encoded_json(value: Any) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _case(requests: list[Any], expectations: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "challenge": {
            "requests": [{"body_base64": _encoded_json(body)} for body in requests]
        },
        "context": {"expectations": expectations},
    }


def build_cases(run_seed: str) -> list[dict[str, Any]]:
    digest = hashlib.sha256(("hf-model-inference\0" + run_seed).encode()).digest()
    hidden = (
        (POSITIVE_TEXTS[digest[0] % len(POSITIVE_TEXTS)], "positive"),
        (NEGATIVE_TEXTS[digest[1] % len(NEGATIVE_TEXTS)], "negative"),
    )
    return [
        _case(
            [{"text": text} for text, _ in SOURCE_TEXTS],
            [{"kind": "sentiment", "label": label} for _, label in SOURCE_TEXTS],
        ),
        _case(
            [{"text": text} for text, _ in hidden],
            [{"kind": "sentiment", "label": label} for _, label in hidden],
        ),
        _case(
            [{"invalid_field": "This should cause an error"}],
            [{"kind": "error", "label": ""}],
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


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json_body(encoded: Any) -> Any:
    raw = _decode(encoded)
    return json.loads(
        raw.decode("utf-8", errors="strict"),
        parse_constant=_reject_constant,
        object_pairs_hook=_pairs,
    )


def _sentiment_matches(body: Any, label: str) -> bool:
    if not isinstance(body, dict) or body.get("sentiment") != label:
        return False
    confidence = body.get("confidence")
    if not isinstance(confidence, dict):
        return False
    positive = confidence.get("positive")
    negative = confidence.get("negative")
    if type(positive) is not float or type(negative) is not float:
        return False
    if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in (positive, negative)):
        return False
    return positive > negative if label == "positive" else negative > positive


class SentimentServiceOracle:
    def __init__(self) -> None:
        self.cases: list[dict[str, Any]] = []
        self.case_index = 0
        self.evaluated = 0
        self.evaluation_ids: set[str] = set()
        self.passed = True
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
        self.passed = False
        self.failures.append(category)

    def evaluate_case(self, context: dict[str, Any], evidence: dict[str, Any]) -> None:
        self.evaluated += 1
        if evidence.get("status") != "observed":
            failure = evidence.get("failure")
            code = failure.get("code") if isinstance(failure, dict) else None
            self.fail(str(code or "service_execution_failed"))
            return
        evaluation_id = evidence.get("evaluation_id")
        if not isinstance(evaluation_id, str) or evaluation_id in self.evaluation_ids:
            self.fail("evaluation_not_fresh")
        else:
            self.evaluation_ids.add(evaluation_id)
        observation = evidence.get("observation")
        if not isinstance(observation, dict):
            self.fail("invalid_observation")
            return
        try:
            _decode(observation.get("stdout_base64"))
            _decode(observation.get("stderr_base64"))
        except ValueError:
            self.fail("invalid_observation")
            return
        if (
            observation.get("server_started") is not True
            or observation.get("process_running") is not True
            or observation.get("process_exit") != -1
            or observation.get("output_too_large") is not False
        ):
            self.fail("service_not_running")
        addresses = observation.get("listen_ipv4")
        if not isinstance(addresses, list) or "0.0.0.0" not in addresses:
            self.fail("service_not_bound_to_all_hosts")

        expectations = context.get("expectations")
        responses = observation.get("responses")
        if not isinstance(expectations, list) or not isinstance(responses, list):
            self.fail("invalid_observation")
            return
        if len(responses) != len(expectations):
            self.fail("incorrect_response_count")
            return
        for expected, response in zip(expectations, responses):
            if not isinstance(expected, dict) or not isinstance(response, dict):
                self.fail("invalid_observation")
                continue
            if response.get("body_too_large") is not False or response.get("error") != "":
                self.fail("invalid_http_response")
                continue
            try:
                body = _json_body(response.get("body_base64"))
            except (UnicodeError, ValueError, json.JSONDecodeError):
                self.fail("invalid_json_response")
                continue
            if expected.get("kind") == "error":
                if (
                    response.get("status") != 400
                    or not isinstance(body, dict)
                    or not isinstance(body.get("error"), str)
                    or not body["error"]
                ):
                    self.fail("incorrect_error_response")
            elif response.get("status") != 200 or not _sentiment_matches(
                body, str(expected.get("label"))
            ):
                self.fail("incorrect_sentiment_response")

    def verdict(self) -> dict[str, Any]:
        behavior = (
            len(self.cases) == 3
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
                        "Sentiment service satisfied the bounded scenarios"
                        if behavior
                        else "Sentiment service did not satisfy the task"
                    ),
                    "failure_categories": sorted(set(self.failures))[:20],
                },
            },
        }


def main() -> None:
    oracle = SentimentServiceOracle()
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
                    != {"max_cases": 3, "max_case_bytes": 32_768}
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
