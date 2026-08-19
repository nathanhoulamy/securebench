"""Deterministic audits of v2 routing and security contracts."""

from __future__ import annotations

from dataclasses import dataclass

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
from securebench.candidates.capture import FRAMEWORK_PROTECTED_PATTERNS
from securebench.errors import ConfigError
from securebench.tasks import BenchmarkTask
from securebench.workspaces.materialization import VisibilityAwareMaterializer


@dataclass(frozen=True)
class StaticAuditContext:
    pack: BenchmarkPack
    target: str
    limit: int | None = None


def run_static_checks(context: StaticAuditContext) -> tuple[AuditFinding, ...]:
    tasks = tuple(compile_benchmark_pack(context.pack, limit=context.limit))
    findings: list[AuditFinding] = []
    for task in tasks:
        findings.extend(_task_findings(task))
    findings.append(_protected_paths_finding())
    return tuple(findings)


def _task_findings(task: BenchmarkTask) -> tuple[AuditFinding, ...]:
    findings = []
    views = {
        "agent": task.view_for("agent"),
        "evaluation_runtime": task.view_for("evaluation_runtime"),
        "oracle": task.view_for("oracle"),
    }
    violations = {
        "agent": [resource.name for resource in views["agent"].resources if resource.visibility != "public"],
        "evaluation_runtime": [
            resource.name
            for resource in views["evaluation_runtime"].resources
            if resource.visibility == "hidden"
        ],
        "oracle": [
            resource.name
            for resource in views["oracle"].resources
            if resource.visibility == "evaluation_inputs"
        ],
    }
    findings.append(
        _finding(
            check_id=f"static.visibility.{task.id}",
            vulnerability=VISIBILITY_BYPASS,
            family=task.family,
            status="failed" if any(violations.values()) else "passed",
            message="component views obey the three visibility lanes",
            evidence={"violations": violations},
            recommendation="Keep public, runtime, and host sources in distinct manifest roots.",
        )
    )
    try:
        plan = VisibilityAwareMaterializer().build_plan(task, "agent")
        non_public = [item.name for item in plan.resources if item.visibility != "public"]
        error = None
    except (ConfigError, ValueError) as exc:
        non_public = []
        error = str(exc)
    findings.append(
        _finding(
            check_id=f"static.materialization.{task.id}",
            vulnerability=MATERIALIZATION_ESCAPE,
            family=task.family,
            status="failed" if error or non_public else "passed",
            message="Agent materialization contains public resources only",
            evidence={"non_public_resources": non_public, "error": error},
            recommendation="Fix unsafe public mounts or compiled resource descriptors.",
        )
    )
    summaries = task.resource_summary()
    leaked = [
        item.get("name")
        for item in summaries
        if item.get("visibility") != "public" and item.get("redacted") is not True
    ]
    findings.append(
        _finding(
            check_id=f"static.result_redaction.{task.id}",
            vulnerability=ANSWER_LEAKAGE,
            family=task.family,
            status="failed" if leaked else "passed",
            message="non-public resource summaries are redacted",
            evidence={"unredacted_resources": leaked},
            recommendation="Persist digests and public diagnostics, never raw host/runtime values.",
        )
    )
    provenance_missing = not all(
        value.startswith("sha256:")
        for value in (
            task.manifest_digest,
            task.row_digest,
            task.baseline_digest,
            task.verification_digest,
        )
    )
    findings.append(
        _finding(
            check_id=f"static.provenance.{task.id}",
            vulnerability=RESULT_INTEGRITY_GAP,
            family=task.family,
            status="failed" if provenance_missing else "passed",
            message="compiled task binds row, baseline, and verification inputs",
            evidence={"missing": provenance_missing},
            recommendation="Keep provenance digests in every result envelope.",
        )
    )
    return tuple(findings)


def _protected_paths_finding() -> AuditFinding:
    required = {".git/**", ".securebench/**", "securebench/**"}
    missing = sorted(required - set(FRAMEWORK_PROTECTED_PATTERNS))
    return _finding(
        check_id="static.candidate.protected_paths",
        vulnerability=TEST_INFRA_TAMPERING,
        family="all",
        status="failed" if missing else "passed",
        message="framework-owned patch paths are protected independently of rows",
        evidence={"missing_patterns": missing},
        recommendation="Candidate rows must never weaken framework-owned protected paths.",
    )


def _finding(
    *,
    check_id: str,
    vulnerability: str,
    family: str,
    status: str,
    message: str,
    evidence: dict[str, object],
    recommendation: str,
) -> AuditFinding:
    entry = catalog_entry(vulnerability)
    return AuditFinding(
        id=check_id,
        vulnerability=vulnerability,
        family=family,
        severity=entry.severity,
        status=status,  # type: ignore[arg-type]
        message=message,
        evidence=evidence,
        recommendation=recommendation,
    )
