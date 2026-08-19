import json
from pathlib import Path

from securebench.audit.report import write_json_report
from securebench.audit.runner import audit_self
from securebench.audit.static_checks import StaticAuditContext, run_static_checks
from securebench.benchmark_pack import load_benchmark_pack


ROOT = Path(__file__).resolve().parents[2]


def test_static_checks_pass_reference_v2_pack():
    root = ROOT / "benchmarks" / "terminal-bench"
    pack = load_benchmark_pack(root / "manifest-v2.yaml", root / "tasks-v2.jsonl")

    findings = run_static_checks(StaticAuditContext(pack=pack, target="terminal-bench-v2"))

    assert findings
    assert not [finding for finding in findings if finding.status == "failed"]
    assert any(finding.id.startswith("static.visibility.") for finding in findings)
    assert any(finding.id.startswith("static.materialization.") for finding in findings)
    assert any(finding.id == "static.candidate.protected_paths" for finding in findings)


def test_audit_self_writes_deterministic_sanitized_json(tmp_path):
    report = audit_self(output_dir=tmp_path)
    output_path = write_json_report(report, tmp_path)
    data = json.loads(output_path.read_text())

    assert data["run_id"] == "audit-self"
    assert data["summary"]["failed"] == 0
    assert data["findings"] == sorted(data["findings"], key=lambda item: item["id"])
