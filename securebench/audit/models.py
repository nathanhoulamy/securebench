"""Shared audit result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AuditStatus = Literal["passed", "failed", "warning", "skipped", "not_applicable"]
AuditSeverity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class AuditFinding:
    """One audit check outcome."""

    id: str
    vulnerability: str
    family: str
    severity: AuditSeverity
    status: AuditStatus
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "failed"


@dataclass(frozen=True)
class AuditSummary:
    """Aggregate audit report counts."""

    total: int
    passed: int
    failed: int
    warnings: int
    skipped: int
    not_applicable: int

    @property
    def status(self) -> str:
        return "failed" if self.failed else "passed"


@dataclass(frozen=True)
class AuditReport:
    """Serializable audit report."""

    run_id: str
    target: str
    findings: tuple[AuditFinding, ...]

    @property
    def summary(self) -> AuditSummary:
        return AuditSummary(
            total=len(self.findings),
            passed=sum(1 for finding in self.findings if finding.status == "passed"),
            failed=sum(1 for finding in self.findings if finding.status == "failed"),
            warnings=sum(1 for finding in self.findings if finding.status == "warning"),
            skipped=sum(1 for finding in self.findings if finding.status == "skipped"),
            not_applicable=sum(1 for finding in self.findings if finding.status == "not_applicable"),
        )

    @property
    def failed(self) -> bool:
        return self.summary.failed > 0
