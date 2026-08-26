"""Host-only Oracle for async concurrency and cancellation behavior."""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


CONCURRENCY_CHECK = "concurrency_behavior"
CANCELLATION_CHECK = "cancellation_behavior"
LEDGER_TYPE = "securebench.append-only-event-ledger/v1"
SUPERVISOR_TYPE = "securebench.process-supervisor/v1"
SIGNAL_AFTER_MS = 500


def _case(prefix: str, task_count: int, maximum: int, work_ms: int, cleanup_ms: int):
    return {
        "challenge": {
            "nonce_prefix": prefix,
            "task_count": task_count,
            "max_concurrent": maximum,
            "work_ms": work_ms,
            "cleanup_ms": cleanup_ms,
        },
        "context": {
            "nonce_prefix": prefix,
            "task_count": task_count,
            "max_concurrent": maximum,
            "work_ms": work_ms,
            "cleanup_ms": cleanup_ms,
        },
    }


class AsyncTaskOracle:
    def __init__(self) -> None:
        self.cases: dict[str, list[dict[str, Any]]] = {}
        self.indices: dict[str, int] = {}
        self.evaluated: dict[str, int] = {}
        self.failures: dict[str, list[str]] = {}

    def initialize(self, request: dict[str, Any]) -> None:
        seed = str(request.get("run_seed", "seed")).encode("utf-8")
        prefix = hashlib.sha256(seed).hexdigest()[:12]
        self.cases = {
            CONCURRENCY_CHECK: [
                _case(prefix + "a", 2, 2, 600, 200),
                _case(prefix + "b", 2, 1, 600, 200),
            ],
            CANCELLATION_CHECK: [
                _case(prefix + "c", 2, 3, 2000, 200),
                _case(prefix + "d", 2, 2, 2000, 200),
                _case(prefix + "e", 3, 2, 2000, 200),
            ],
        }
        self.indices = {check_id: 0 for check_id in self.cases}
        self.evaluated = {check_id: 0 for check_id in self.cases}
        self.failures = {check_id: [] for check_id in self.cases}

    def next_case(self, check_id: str) -> dict[str, Any]:
        cases = self.cases[check_id]
        index = self.indices[check_id]
        if index >= len(cases):
            return {"type": "exhausted"}
        case = cases[index]
        self.indices[check_id] = index + 1
        context = {"index": index, **case["context"]}
        return {
            "type": "case",
            "challenge": case["challenge"],
            "case_context": context,
        }

    def evaluate(
        self,
        check_id: str,
        context: dict[str, Any],
        evidence: dict[str, Any],
    ) -> None:
        self.evaluated[check_id] += 1
        label = f"case_{context.get('index', -1)}"
        if evidence.get("status") != "observed":
            self._fail(check_id, label + ":candidate_error")
            return
        observation = evidence.get("observation")
        if (
            not isinstance(observation, dict)
            or observation.get("child_started") is not True
            or observation.get("timed_out") is not False
        ):
            self._fail(check_id, label + ":candidate_process")
            return
        if check_id == CONCURRENCY_CHECK and observation.get("child_exit_code") != 0:
            self._fail(check_id, label + ":candidate_exit")
        if check_id == CANCELLATION_CHECK and (
            observation.get("signal_received") is not True
            or observation.get("signal_forwarded") is not True
        ):
            self._fail(check_id, label + ":signal_forwarding")
        helpers = evidence.get("trusted_helper_evidence")
        if not isinstance(helpers, dict):
            self._fail(check_id, label + ":helper_evidence")
            return
        ledger = self._correlated_helper(
            check_id, label, evidence, helpers.get("lifecycle"), LEDGER_TYPE
        )
        supervisor = self._correlated_helper(
            check_id,
            label,
            evidence,
            helpers.get("process_control"),
            SUPERVISOR_TYPE,
        )
        if ledger is None or supervisor is None:
            return
        events = ledger.get("value", {}).get("events")
        process = supervisor.get("value", {}).get("process")
        signals = supervisor.get("value", {}).get("signals")
        if (
            not isinstance(events, list)
            or not isinstance(process, dict)
            or not isinstance(signals, list)
        ):
            self._fail(check_id, label + ":helper_shape")
            return
        if ledger.get("truncated") is not False or supervisor.get("truncated") is not False:
            self._fail(check_id, label + ":helper_truncated")
            return
        if (
            process.get("container_started") is not True
            or process.get("exit_code") != 0
            or process.get("timed_out") is not False
        ):
            self._fail(check_id, label + ":process_lifecycle")
        if check_id == CONCURRENCY_CHECK:
            if signals:
                self._fail(check_id, label + ":unexpected_signal")
            self._evaluate_concurrency(check_id, label, context, events, process)
        else:
            self._evaluate_cancellation(
                check_id, label, context, events, process, signals
            )

    def _correlated_helper(
        self,
        check_id: str,
        label: str,
        evidence: dict[str, Any],
        helper: Any,
        helper_type: str,
    ) -> dict[str, Any] | None:
        if not isinstance(helper, dict):
            self._fail(check_id, label + ":helper_missing")
            return None
        challenge = evidence.get("challenge")
        if (
            not isinstance(challenge, dict)
            or helper.get("type") != helper_type
            or helper.get("challenge_id") != challenge.get("id")
            or helper.get("evaluation_id") != evidence.get("evaluation_id")
        ):
            self._fail(check_id, label + ":helper_correlation")
            return None
        return helper

    def _validated_events(
        self,
        check_id: str,
        label: str,
        context: dict[str, Any],
        events: list[Any],
    ) -> list[dict[str, Any]] | None:
        retained: list[dict[str, Any]] = []
        seen_nonces: set[str] = set()
        for record in events:
            if (
                not isinstance(record, dict)
                or record.get("accepted") is not True
                or record.get("authenticated") is not True
                or record.get("path_matched") is not True
                or record.get("method") != "POST"
                or record.get("event_valid") is not True
            ):
                self._fail(check_id, label + ":rejected_or_invalid_event")
                return None
            event = record.get("event")
            data = record.get("data")
            nonce = record.get("nonce")
            if event == "adapter.signal_forwarded":
                expected_nonce = f"{context['nonce_prefix']}_signal"
                if (
                    data != "SIGINT"
                    or nonce != expected_nonce
                    or nonce in seen_nonces
                ):
                    self._fail(check_id, label + ":signal_marker")
                    return None
                seen_nonces.add(nonce)
                retained.append(record)
                continue
            if event not in {
                "task.started",
                "task.completed",
                "task.cancelled",
                "task.cleaned",
            }:
                self._fail(check_id, label + ":unexpected_event")
                return None
            if not isinstance(data, str) or not data.isascii() or not data.isdigit():
                self._fail(check_id, label + ":invalid_task_id")
                return None
            task_id = int(data)
            if task_id < 0 or task_id >= context["task_count"]:
                self._fail(check_id, label + ":invalid_task_id")
                return None
            phase = event.rsplit(".", 1)[1]
            suffix = {
                "started": "start",
                "completed": "complete",
                "cancelled": "cancel",
                "cleaned": "clean",
            }[phase]
            expected_nonce = f"{context['nonce_prefix']}_{task_id}_{suffix}"
            if nonce != expected_nonce or nonce in seen_nonces:
                self._fail(check_id, label + ":nonce_or_duplicate")
                return None
            seen_nonces.add(nonce)
            retained.append(record)
        return retained

    def _evaluate_concurrency(
        self,
        check_id: str,
        label: str,
        context: dict[str, Any],
        raw_events: list[Any],
        process: dict[str, Any],
    ) -> None:
        events = self._validated_events(check_id, label, context, raw_events)
        if events is None:
            return
        task_count = context["task_count"]
        if len(events) != task_count * 3:
            self._fail(check_id, label + ":event_count")
            return
        per_task: dict[int, dict[str, int]] = {index: {} for index in range(task_count)}
        active = 0
        peak = 0
        for record in events:
            task_id = int(record["data"])
            phase = record["event"].rsplit(".", 1)[1]
            if phase in per_task[task_id]:
                self._fail(check_id, label + ":duplicate_phase")
                return
            per_task[task_id][phase] = record["elapsed_us"]
            if phase == "started":
                active += 1
                peak = max(peak, active)
            elif phase == "cleaned":
                active -= 1
                if active < 0:
                    self._fail(check_id, label + ":event_order")
                    return
        if active != 0 or peak != min(task_count, context["max_concurrent"]):
            self._fail(check_id, label + ":concurrency_limit")
        for phases in per_task.values():
            if set(phases) != {"started", "completed", "cleaned"}:
                self._fail(check_id, label + ":missing_phase")
                continue
            if not phases["started"] < phases["completed"] < phases["cleaned"]:
                self._fail(check_id, label + ":event_order")
            if phases["completed"] - phases["started"] < context["work_ms"] * 900:
                self._fail(check_id, label + ":work_timing")
            if phases["cleaned"] - phases["completed"] < context["cleanup_ms"] * 900:
                self._fail(check_id, label + ":cleanup_timing")
        minimum_waves = (task_count + context["max_concurrent"] - 1) // context["max_concurrent"]
        minimum_ms = minimum_waves * (context["work_ms"] + context["cleanup_ms"])
        if process.get("duration_ms", 0) < minimum_ms * 0.85:
            self._fail(check_id, label + ":process_too_fast")

    def _evaluate_cancellation(
        self,
        check_id: str,
        label: str,
        context: dict[str, Any],
        raw_events: list[Any],
        process: dict[str, Any],
        signals: list[Any],
    ) -> None:
        events = self._validated_events(check_id, label, context, raw_events)
        if events is None:
            return
        expected_started = min(context["task_count"], context["max_concurrent"])
        started = [record for record in events if record["event"] == "task.started"]
        completed = [record for record in events if record["event"] == "task.completed"]
        cancelled = [record for record in events if record["event"] == "task.cancelled"]
        cleaned = [record for record in events if record["event"] == "task.cleaned"]
        signal_markers = [
            record for record in events if record["event"] == "adapter.signal_forwarded"
        ]
        if (
            len(started) != expected_started
            or len(cancelled) != expected_started
            or len(cleaned) != expected_started
        ):
            self._fail(check_id, label + ":cancelled_task_count")
        if len(signal_markers) != 1:
            self._fail(check_id, label + ":signal_marker")
        else:
            signal_position = events.index(signal_markers[0])
            if any(events.index(record) > signal_position for record in started):
                self._fail(check_id, label + ":task_started_after_signal")
            if any(events.index(record) < signal_position for record in cancelled):
                self._fail(check_id, label + ":cancellation_before_signal")
            if any(events.index(record) < signal_position for record in cleaned):
                self._fail(check_id, label + ":cleanup_before_signal")
        if completed:
            self._fail(check_id, label + ":tasks_completed_after_signal")
        if {record["data"] for record in started} != {record["data"] for record in cleaned}:
            self._fail(check_id, label + ":cleanup_set")
        if {record["data"] for record in started} != {
            record["data"] for record in cancelled
        }:
            self._fail(check_id, label + ":cancellation_set")
        started_at = {record["data"]: record["elapsed_us"] for record in started}
        for record in cleaned:
            elapsed = record["elapsed_us"] - started_at.get(record["data"], record["elapsed_us"])
            if elapsed < context["cleanup_ms"] * 900:
                self._fail(check_id, label + ":cleanup_timing")
        if len(events) != expected_started * 3 + 1:
            self._fail(check_id, label + ":event_count")
        if len(signals) != 1:
            self._fail(check_id, label + ":signal_count")
            return
        observed = signals[0]
        if (
            not isinstance(observed, dict)
            or observed.get("signal") != "SIGINT"
            or observed.get("scheduled_after_ms") != SIGNAL_AFTER_MS
            or observed.get("delivered") is not True
            or observed.get("attempted_after_ms", -1) < SIGNAL_AFTER_MS
        ):
            self._fail(check_id, label + ":signal_delivery")
            return
        if process.get("duration_ms", 0) < observed["attempted_after_ms"] + 150:
            self._fail(check_id, label + ":cleanup_after_signal")

    def _fail(self, check_id: str, value: str) -> None:
        self.failures[check_id].append(value)

    def verdict(self) -> dict[str, Any]:
        outcomes = {
            check_id: (
                self.evaluated.get(check_id) == len(cases)
                and not self.failures.get(check_id)
            )
            for check_id, cases in self.cases.items()
        }
        passed = bool(outcomes) and all(outcomes.values())
        failures = sorted(
            f"{check_id}:{failure}"
            for check_id, values in self.failures.items()
            for failure in values
        )
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": outcomes,
                "public_diagnostics": {
                    "message": (
                        "Concurrency and cancellation behavior matched"
                        if passed
                        else "Concurrency or cancellation behavior diverged"
                    ),
                    "failure_categories": failures[:24],
                },
            },
        }


def main() -> None:
    oracle = AsyncTaskOracle()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation == "initialize":
                oracle.initialize(request)
                response = {"type": "ack"}
            elif operation == "next_case":
                response = oracle.next_case(request["check_id"])
            elif operation == "evaluate_case":
                oracle.evaluate(
                    request["check_id"],
                    request.get("case_context", {}),
                    request.get("evidence", {}),
                )
                response = {"type": "ack"}
            elif operation == "finalize":
                response = oracle.verdict()
            elif operation == "evaluate_artifact":
                response = {"type": "ack"}
            else:
                raise ValueError("unsupported operation")
        except Exception:
            response = {"type": "error"}
        print(json.dumps(response, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
