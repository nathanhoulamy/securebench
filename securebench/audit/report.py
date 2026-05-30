"""Audit report serialization and terminal rendering."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from securebench.audit.models import AuditReport


DEFAULT_REPORT_FILENAME = "audit-report.json"


def write_json_report(report: AuditReport, output_dir: str | Path) -> Path:
    """Write a deterministic JSON audit report."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / DEFAULT_REPORT_FILENAME
    data = {
        "run_id": report.run_id,
        "target": report.target,
        "summary": asdict(report.summary),
        "findings": [asdict(finding) for finding in sorted(report.findings, key=lambda item: item.id)],
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path


def render_text_summary(report: AuditReport, output_path: str | Path) -> str:
    """Return a concise human-readable audit summary."""
    summary = report.summary
    lines = [
        "securebench audit: "
        f"run_id={report.run_id} target={report.target} status={summary.status} "
        f"total={summary.total} passed={summary.passed} failed={summary.failed} "
        f"warnings={summary.warnings} skipped={summary.skipped} output={output_path}",
    ]
    for finding in sorted(report.findings, key=lambda item: (item.status != "failed", item.id)):
        if finding.status in {"failed", "warning"}:
            lines.append(f"  [{finding.status.upper()}] {finding.id}: {finding.message}")
    return "\n".join(lines)
