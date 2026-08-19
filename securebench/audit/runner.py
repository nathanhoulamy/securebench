"""High-level v2 audit orchestration."""

from __future__ import annotations

from pathlib import Path

from securebench.audit.models import AuditReport
from securebench.audit.static_checks import StaticAuditContext, run_static_checks
from securebench.benchmark_pack import load_benchmark_pack
from securebench.tester_config import TesterConfig


def audit_config(
    config: TesterConfig,
    *,
    output_dir: str | Path | None = None,
    limit: int | None = None,
) -> AuditReport:
    pack = load_benchmark_pack(config.benchmark.manifest, config.benchmark.tasks)
    findings = run_static_checks(
        StaticAuditContext(pack=pack, target=str(config.benchmark.manifest), limit=limit)
    )
    return AuditReport(
        run_id=f"{config.run.id}-audit",
        target=str(config.benchmark.manifest),
        findings=findings,
    )


def audit_self(
    *,
    output_dir: str | Path,
) -> AuditReport:
    """Audit the checked-in v2 reference pack; dynamic attacks live in tests."""
    root = Path(__file__).resolve().parents[2] / "benchmarks" / "terminal-bench"
    pack = load_benchmark_pack(root / "manifest-v2.yaml", root / "tasks-v2.jsonl")
    findings = run_static_checks(StaticAuditContext(pack=pack, target=str(root)))
    return AuditReport(run_id="audit-self", target=str(root), findings=findings)
