import json

from securebench.audit.report import write_json_report
from securebench.audit.runner import audit_self
from securebench.audit.smoke import SMOKE_CASES
from securebench.audit.static_checks import StaticAuditContext, run_static_checks
from securebench.benchmark_pack import load_benchmark_pack


def test_static_checks_pass_builtin_multiple_choice_pack():
    pack = load_benchmark_pack(
        "benchmarks/audit/multiple-choice/manifest.yaml",
        "benchmarks/audit/multiple-choice/tasks.jsonl",
    )

    findings = run_static_checks(StaticAuditContext(pack=pack, target="multiple-choice"))

    assert findings
    assert not [finding for finding in findings if finding.status == "failed"]
    assert any(finding.id.startswith("static.agent_payload.") for finding in findings)
    assert any(finding.id.startswith("static.materialization.") for finding in findings)


def test_audit_self_static_only_writes_deterministic_json(tmp_path):
    report = audit_self(output_dir=tmp_path, static_only=True)
    output_path = write_json_report(report, tmp_path)

    data = json.loads(output_path.read_text())

    assert data["run_id"] == "audit-self"
    assert data["summary"]["failed"] == 0
    assert data["findings"] == sorted(data["findings"], key=lambda item: item["id"])
    assert any(item["id"] == "static.repo_patch.default_policy" for item in data["findings"])


def test_audit_self_skip_docker_records_skipped_smoke(tmp_path):
    report = audit_self(output_dir=tmp_path, skip_docker=True)

    assert any(finding.id == "smoke.docker.skipped" and finding.status == "skipped" for finding in report.findings)
    assert report.summary.failed == 0


def test_aggressive_family_specific_smoke_cases_are_registered():
    case_ids = {case.id for case in SMOKE_CASES}

    assert {
        "smoke.code_completion.hidden_runner_read",
        "smoke.code_completion.stack_introspection",
        "smoke.code_completion.sentinel_forgery",
        "smoke.code_completion.import_hook_tamper",
        "smoke.repo_patch.config_tamper",
        "smoke.repo_patch.shell_runner_tamper",
        "smoke.repo_patch.path_traversal",
        "smoke.repo_patch.preserved_path_strip",
        "smoke.terminal_task.fake_pytest_wrapper",
        "smoke.terminal_task.output_only_bypass",
    } <= case_ids
