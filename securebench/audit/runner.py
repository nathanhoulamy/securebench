"""High-level audit orchestration."""

from __future__ import annotations

from pathlib import Path

from securebench.audit.models import AuditReport
from securebench.audit.smoke import docker_available, run_smoke_checks
from securebench.audit.static_checks import StaticAuditContext, run_static_checks
from securebench.benchmark_pack import load_benchmark_pack
from securebench.errors import ConfigError
from securebench.tester_config import TesterConfig


def audit_config(
    config: TesterConfig,
    *,
    output_dir: str | Path | None = None,
    limit: int | None = None,
) -> AuditReport:
    """Audit one tester config using deterministic static checks."""
    pack = load_benchmark_pack(config.benchmark.manifest, config.benchmark.tasks)
    findings = run_static_checks(
        StaticAuditContext(
            pack=pack,
            target=str(config.benchmark.manifest),
            limit=limit,
        )
    )
    return AuditReport(run_id=f"{config.run.id}-audit", target=str(config.benchmark.manifest), findings=findings)


def audit_self(
    *,
    output_dir: str | Path,
    static_only: bool = False,
    skip_docker: bool = False,
    audit_benchmarks_dir: str | Path | None = None,
) -> AuditReport:
    """Run built-in SecureBench robustness checks."""
    benchmarks_dir = Path(audit_benchmarks_dir) if audit_benchmarks_dir is not None else _default_audit_benchmarks_dir()
    all_findings = []
    for pack_dir in sorted(path for path in benchmarks_dir.iterdir() if path.is_dir()):
        pack = load_benchmark_pack(pack_dir / "manifest.yaml", pack_dir / "tasks.jsonl")
        all_findings.extend(
            run_static_checks(
                StaticAuditContext(
                    pack=pack,
                    target=str(pack_dir),
                )
            )
        )

    if not static_only:
        if skip_docker:
            all_findings.append(_docker_skipped_finding())
        elif not docker_available():
            raise ConfigError("Docker is required for audit-self dynamic smoke checks; use --static-only or --skip-docker")
        else:
            all_findings.extend(run_smoke_checks(audit_benchmarks_dir=benchmarks_dir, output_dir=Path(output_dir)))

    return AuditReport(run_id="audit-self", target=str(benchmarks_dir), findings=tuple(all_findings))


def _default_audit_benchmarks_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "benchmarks" / "audit"


def _docker_skipped_finding():
    from securebench.audit.catalog import NETWORK_EGRESS, catalog_entry
    from securebench.audit.models import AuditFinding

    entry = catalog_entry(NETWORK_EGRESS)
    return AuditFinding(
        id="smoke.docker.skipped",
        vulnerability=NETWORK_EGRESS,
        family="all",
        severity=entry.severity,
        status="skipped",
        message="Docker-dependent smoke checks were skipped by explicit request",
        evidence={"skip_docker": True},
        recommendation="Run audit-self without --skip-docker in CI.",
    )
