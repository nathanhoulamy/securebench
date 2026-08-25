from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import CandidateStore, HostWorkspaceFilesystem, capture_file_bundle
from securebench.execution_profiles import validate_executable_task
from securebench.verification import VerificationEngine
from securebench.verification.json_data import json_digest
from securebench.verification.models import ChallengeEvidence, TrustedHelperEvidence
from securebench.verification.oracle import OracleProcessSession


ROOT = Path(__file__).resolve().parents[1]


def compiled_tasks(pack_name: str):
    root = ROOT / "benchmarks" / pack_name
    pack = load_benchmark_pack(root / "manifest-v2.yaml", root / "tasks-v2.jsonl")
    return {task.id: task for task in compile_benchmark_pack(pack)}


def verify_file(tmp_path: Path, task_id: str, filename: str, content: str):
    task = compiled_tasks("terminal-bench")[task_id]
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / filename).write_text(content, encoding="utf-8")
    store = CandidateStore(tmp_path / "store")
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
    )
    return VerificationEngine().verify(task, candidate, store, run_seed="pilot-test-seed")


def test_all_first_wave_rows_compile_and_pass_executable_preflight():
    terminal = compiled_tasks("terminal-bench")
    deep = compiled_tasks("deep-swe")
    assert set(terminal) >= {
        "terminal-bench/constraints-scheduling",
        "terminal-bench/sqlite-db-truncate",
        "terminal-bench/vulnerable-secret",
    }
    assert set(deep) == {
        "deep-swe/cattrs-partial-structuring-recovery",
        "deep-swe/fd-deterministic-multi-key-sorting",
        "deep-swe/updo-policy-alerting",
    }
    for task in (*terminal.values(), *deep.values()):
        validate_executable_task(task)
        assert "@sha256:" in task.environment.image


def test_sqlite_recovery_preserves_source_threshold(tmp_path):
    rows = [
        {"word": "testword02", "value": 10},
        {"word": "testword03", "value": 25},
        {"word": "testword04", "value": 42},
        {"word": "testword05", "value": 50},
        {"word": "testword06", "value": 75},
        {"word": "testword07", "value": 99},
        {"word": "testword08", "value": 99.99},
    ]
    passed = verify_file(
        tmp_path / "pass",
        "terminal-bench/sqlite-db-truncate",
        "recover.json",
        json.dumps([*rows, {"word": "untrusted-extra", "value": 1}]),
    )
    failed = verify_file(
        tmp_path / "fail",
        "terminal-bench/sqlite-db-truncate",
        "recover.json",
        json.dumps([*rows[:6], rows[0], rows[0]]),
    )
    assert passed.status == "passed"
    assert failed.status == "failed"
    assert "insufficient_recovery" in failed.public_diagnostics["failure_categories"]


def test_sqlite_recovery_ignores_candidate_verdict_claims(tmp_path):
    rows = [
        {"word": word, "value": value, "verdict": True}
        for word, value in (
            ("testword02", 10), ("testword03", 25), ("testword04", 42),
            ("testword05", 50), ("testword06", 75), ("testword07", 99),
            ("testword08", 99.99),
        )
    ]
    passed = verify_file(
        tmp_path,
        "terminal-bench/sqlite-db-truncate",
        "recover.json",
        json.dumps(rows),
    )
    assert passed.status == "passed"


def test_vulnerable_secret_accepts_only_exact_extracted_key(tmp_path):
    passed = verify_file(
        tmp_path / "pass",
        "terminal-bench/vulnerable-secret",
        "results.txt",
        "  FLAG{b4ff3r_0v3rfl0w_m4st3r_k3y_2024}\n",
    )
    failed = verify_file(
        tmp_path / "fail",
        "terminal-bench/vulnerable-secret",
        "results.txt",
        "FLAG{plausible_but_wrong}",
    )
    assert passed.status == "passed"
    assert failed.status == "failed"
    assert "incorrect_secret" in failed.public_diagnostics["failure_categories"]


def evidence(task, case, observation, index, helpers=()):
    challenge_id = f"challenge-test-{index}"
    evaluation_id = f"evaluation-test-{index}"
    correlated = tuple(
        TrustedHelperEvidence(
            name=name,
            type="securebench.http-request-recorder/v1",
            challenge_id=challenge_id,
            evaluation_id=evaluation_id,
            value=value,
        )
        for name, value in helpers
    )
    return ChallengeEvidence(
        check_id=task.verification.checks[0].id,
        challenge_id=challenge_id,
        evaluation_id=evaluation_id,
        challenge_index=index,
        challenge_digest=json_digest(case.challenge),
        status="observed",
        exit_status=0,
        observation=observation,
        observation_bytes=len(json.dumps(observation)),
        trusted_helper_evidence=correlated,
    )


def drive_cattrs(task, *, mutate=False):
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="cattrs-qualification")
        index = 0
        while (case := session.next_challenge("partial_structuring_behavior", "host.task_oracle", {"max_cases": 12, "max_case_bytes": 32768})) is not None:
            snapshots = []
            for wanted in case.context["expected"]:
                snapshots.append({
                    "value_json": json.dumps(wanted["value"], sort_keys=True, separators=(",", ":")),
                    "is_complete": wanted["complete"],
                    "structured_fields": wanted["structured"],
                    "failed_fields": wanted["failed"],
                    "errors_present": bool(wanted["failed"]),
                    "error_fields": wanted["failed"],
                    "error_types": ["ValueError"] * len(wanted["failed"]),
                    "errors_picklable": True,
                    "structured_fields_frozenset": True,
                    "failed_fields_frozenset": True,
                })
            if mutate and index == 4:
                snapshots[0]["failed_fields"] = []
            observation = {
                "status": "observed",
                "api": {"partial_result_exported": True, "top_level_callable": True, "converter_method": True, "base_converter_method": True, "ordinary_structure_success": True, "ordinary_structure_rejects_bad": True},
                "snapshots": snapshots,
                "legacy_error_roundtrips": [
                    {"class_name": name, "before_args_json": "[]", "after_args_json": "[]", "before_message": "same", "after_message": "same", "cause_none": True, "context_none": True, "traceback_none": True}
                    for name in ("StructureHandlerNotFoundError", "ForbiddenExtraKeysError", "ForbiddenExtraKeysError", "ForbiddenExtraKeysError", "BaseValidationError", "IterableValidationError", "ClassValidationError")
                ],
                "factory_calls": max((wanted.get("factory_calls", 0) for wanted in case.context["expected"]), default=0),
                "error_type": "", "error_message": "",
            }
            session.evaluate_challenge("partial_structuring_behavior", case.context, evidence(task, case, observation, index))
            index += 1
        return session.finalize()


def drive_fd(task, *, mutate=False):
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="fd-qualification")
        index = 0
        while (case := session.next_challenge("deterministic_sorting_behavior", "host.task_oracle", {"max_cases": 2, "max_case_bytes": 131072})) is not None:
            results = []
            invalid = {"reverse_requires_sort", "grouping_conflict", "exec_incompatible", "details_incompatible"}
            for item in case.challenge["scenarios"]:
                identifier = item["id"]
                expected = case.context["expected"][identifier]
                if identifier in invalid:
                    lines, repeated, exit_code, stderr = [], [[]], 2, "invalid sorting option"
                elif identifier == "seeded_random":
                    lines = ["c", "a", "d", "b"]
                    repeated, exit_code, stderr = [lines, lines], 0, ""
                elif identifier == "unseeded_random":
                    lines = ["a", "b", "c", "d", "e"]
                    repeated = [lines, ["b", "a", "c", "d", "e"], lines, ["c", "b", "a", "d", "e"]]
                    exit_code, stderr = 0, ""
                else:
                    lines = expected
                    repeated, exit_code, stderr = [lines], 0, ""
                results.append({"id": identifier, "exit_code": exit_code, "stdout_lines": lines, "stderr": stderr, "repeated_stdout_lines": repeated})
            if mutate and index == 0:
                results[0]["stdout_lines"] = list(reversed(results[0]["stdout_lines"]))
            observation = {"build_exit_code": 0, "build_stderr": "", "results": results}
            session.evaluate_challenge("deterministic_sorting_behavior", case.context, evidence(task, case, observation, index))
            index += 1
        return session.finalize()


def recorder_value(expected):
    requests = []
    for token, event in expected:
        payload = {
            "event": event,
            "state": "healthy",
            "previous_state": "healthy",
            "reason": "bounded observed reason",
            "consecutive_failures": 0,
            "consecutive_recoveries": 0,
            "latency_breaches": 0,
            "ssl_expiry_days": -1,
            "region": "pilot-region",
        }
        requests.append({
            "authenticated": True,
            "path_matched": True,
            "method": "POST",
            "headers": [{"name": "X-SecureBench-Token", "value": token}],
            "body_base64": base64.b64encode(json.dumps(payload).encode()).decode(),
        })
    return {"requests": requests}


def drive_updo(task, *, mutate=False):
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="updo-qualification")
        index = 0
        while (case := session.next_challenge("policy_and_delivery_behavior", "host.task_oracle", {"max_cases": 8, "max_case_bytes": 65536})) is not None:
            context = case.context
            decisions = []
            for wanted in context.get("decisions", []):
                decisions.append({**wanted, "reason": "reason" if wanted["event"] else "", "webhook_error": ""})
            if mutate and index == 0:
                decisions[2]["suppressed"] = True
            observation = {
                "status": "observed",
                "decisions": decisions,
                "config_policies": context.get("policies", []),
                "simple_output": " ".join(context.get("contains", [])),
                "run_error": "",
            }
            helper = recorder_value(context.get("requests", []))
            session.evaluate_challenge("policy_and_delivery_behavior", context, evidence(task, case, observation, index, (("webhook", helper),)))
            index += 1
        return session.finalize()


@pytest.mark.parametrize(
    ("row", "driver"),
    [
        ("deep-swe/cattrs-partial-structuring-recovery", drive_cattrs),
        ("deep-swe/fd-deterministic-multi-key-sorting", drive_fd),
        ("deep-swe/updo-policy-alerting", drive_updo),
    ],
)
def test_protocol_oracles_accept_reference_observations_and_reject_targeted_mutants(row, driver):
    task = compiled_tasks("deep-swe")[row]
    reference = driver(task)
    mutant = driver(task, mutate=True)
    assert reference.passed is True
    assert mutant.passed is False
