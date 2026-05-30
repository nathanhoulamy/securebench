"""Deterministic static audit checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from securebench.audit.catalog import (
    ANSWER_LEAKAGE,
    MATERIALIZATION_ESCAPE,
    RESULT_INTEGRITY_GAP,
    TEST_INFRA_TAMPERING,
    VISIBILITY_BYPASS,
    catalog_entry,
)
from securebench.audit.models import AuditFinding
from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import BenchmarkPack
from securebench.candidates import CandidateArtifact
from securebench.errors import ConfigError
from securebench.resources import REDACTED
from securebench.tasks import SecureBenchTask
from securebench.tester_run import candidate_record
from securebench.verifiers.repo_patch import evaluate_candidate_patch_policy
from securebench.workspaces.materialization import VisibilityAwareMaterializer


@dataclass(frozen=True)
class StaticAuditContext:
    """Inputs for static audit checks."""

    pack: BenchmarkPack
    target: str
    limit: int | None = None


SENSITIVE_AGENT_KEYS = (
    "answer",
    "accepted_answers",
    "reference_answer",
    "rubric",
    "tests",
    "canonical_solution",
    "reference_solution",
    "gold_patch",
    "checker",
    "expected_state",
)


def run_static_checks(context: StaticAuditContext) -> tuple[AuditFinding, ...]:
    """Run static checks over a benchmark pack."""
    tasks = tuple(compile_benchmark_pack(context.pack, limit=context.limit))
    findings: list[AuditFinding] = []
    findings.extend(_check_agent_payload_visibility(tasks))
    findings.extend(_check_materialization_visibility(tasks))
    findings.extend(_check_result_redaction(tasks))
    findings.append(_check_repo_patch_default_policy())
    findings.append(_check_result_integrity_metadata(tasks))
    return tuple(findings)


def _finding(
    *,
    check_id: str,
    vulnerability: str,
    family: str,
    status: str,
    message: str,
    evidence: dict[str, object] | None = None,
    recommendation: str = "",
) -> AuditFinding:
    entry = catalog_entry(vulnerability)
    return AuditFinding(
        id=check_id,
        vulnerability=vulnerability,
        family=family,
        severity=entry.severity,
        status=status,  # type: ignore[arg-type]
        message=message,
        evidence={} if evidence is None else evidence,
        recommendation=recommendation,
    )


def _check_agent_payload_visibility(tasks: Iterable[SecureBenchTask]) -> tuple[AuditFinding, ...]:
    findings = []
    for task in tasks:
        payload = task.agent_payload()
        leaked = sorted(key for key in payload if key in SENSITIVE_AGENT_KEYS)
        status = "failed" if leaked else "passed"
        findings.append(
            _finding(
                check_id=f"static.agent_payload.{task.id}",
                vulnerability=VISIBILITY_BYPASS if leaked else ANSWER_LEAKAGE,
                family=task.task_type,
                status=status,
                message=(
                    "agent payload contains sensitive resource keys"
                    if leaked
                    else "agent payload contains only public resource keys"
                ),
                evidence={"task_id": task.id, "leaked_keys": leaked},
                recommendation="Keep answer, verifier, and rubric fields in eval visibility lanes.",
            )
        )
    return tuple(findings)


def _check_materialization_visibility(tasks: Iterable[SecureBenchTask]) -> tuple[AuditFinding, ...]:
    materializer = VisibilityAwareMaterializer()
    findings = []
    for task in tasks:
        try:
            plan = materializer.build_plan(task, "agent")
        except (ConfigError, ValueError) as exc:
            findings.append(
                _finding(
                    check_id=f"static.materialization.{task.id}",
                    vulnerability=MATERIALIZATION_ESCAPE,
                    family=task.task_type,
                    status="failed",
                    message="agent materialization plan could not be built safely",
                    evidence={"task_id": task.id, "error": str(exc)},
                    recommendation="Fix unsafe resource paths or benchmark asset roots.",
                )
            )
            continue
        non_public = sorted(item.name for item in plan.resources if item.visibility != "public")
        findings.append(
            _finding(
                check_id=f"static.materialization.{task.id}",
                vulnerability=MATERIALIZATION_ESCAPE,
                family=task.task_type,
                status="failed" if non_public else "passed",
                message=(
                    "agent materialization includes non-public resources"
                    if non_public
                    else "agent materialization excludes non-public resources"
                ),
                evidence={"task_id": task.id, "non_public_resources": non_public},
                recommendation="Only public resources may be materialized for the agent component.",
            )
        )
    return tuple(findings)


def _check_result_redaction(tasks: Iterable[SecureBenchTask]) -> tuple[AuditFinding, ...]:
    findings = []
    for task in tasks:
        record = candidate_record("audit-static", task, CandidateArtifact(text="audit"))
        hidden_values = record.get("hidden_values")
        summaries = record.get("resource_summary")
        hidden_unredacted = []
        if isinstance(summaries, list):
            hidden_unredacted = [
                str(item.get("name"))
                for item in summaries
                if isinstance(item, dict) and item.get("visibility") != "public" and item.get("redacted") is not True
            ]
        failed = hidden_values != REDACTED or bool(hidden_unredacted)
        findings.append(
            _finding(
                check_id=f"static.result_redaction.{task.id}",
                vulnerability=ANSWER_LEAKAGE,
                family=task.task_type,
                status="failed" if failed else "passed",
                message="result record redacts non-public resource values" if not failed else "result record leaks non-public resource values",
                evidence={"task_id": task.id, "unredacted_resources": hidden_unredacted},
                recommendation="Result serialization must keep hidden and evaluation inputs redacted.",
            )
        )
    return tuple(findings)


def _check_repo_patch_default_policy() -> AuditFinding:
    expected = (
        "tests/test_app.py",
        "conftest.py",
        ".github/workflows/ci.yml",
        "securebench/evaluation_inputs/test.patch",
    )
    denied = []
    missing = []
    for path in expected:
        decision = evaluate_candidate_patch_policy(f"diff --git a/{path} b/{path}\n")
        if path in decision.denied_paths:
            denied.append(path)
        else:
            missing.append(path)
    return _finding(
        check_id="static.repo_patch.default_policy",
        vulnerability=TEST_INFRA_TAMPERING,
        family="repo_patch",
        status="failed" if missing else "passed",
        message="repo-patch default policy denies test infrastructure tampering" if not missing else "repo-patch policy allows sensitive paths",
        evidence={"missing_denials": missing, "denied_paths": denied},
        recommendation="Keep default repo-patch policy fail-closed for tests, CI, dependency files, and SecureBench paths.",
    )


def _check_result_integrity_metadata(tasks: tuple[SecureBenchTask, ...]) -> AuditFinding:
    missing = []
    for task in tasks:
        pack = task.metadata.get("benchmark_pack") if isinstance(task.metadata, dict) else None
        manifest_path = pack.get("manifest_path") if isinstance(pack, dict) else None
        if not isinstance(manifest_path, str) or not manifest_path:
            missing.append(task.id)
    return _finding(
        check_id="static.result_integrity.pack_metadata",
        vulnerability=RESULT_INTEGRITY_GAP,
        family="all",
        status="warning" if missing else "passed",
        message="compiled tasks include benchmark manifest provenance" if not missing else "some tasks lack benchmark manifest provenance",
        evidence={"missing_task_ids": missing},
        recommendation="Add pack and task digests to result metadata in a future hardening pass.",
    )


def default_output_dir(path: str | Path | None, fallback: Path) -> Path:
    """Return a resolved audit output directory."""
    return fallback if path is None else Path(path)
