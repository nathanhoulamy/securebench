import json
from pathlib import Path

from securebench import cli


def test_cli_audit_writes_report(tmp_path, capsys):
    config_path = tmp_path / "tester.yaml"
    output_dir = tmp_path / "audit"
    root = Path.cwd()
    config_path.write_text(
        f"""
schema_version: "0.2"
run:
  id: audit-cli
  output_dir: {tmp_path / "run"}
benchmark:
  manifest: {root / "benchmarks/audit/multiple-choice/manifest.yaml"}
  tasks: {root / "benchmarks/audit/multiple-choice/tasks.jsonl"}
harness:
  type: command
  config:
    command: "printf B"
"""
    )

    exit_code = cli.main(["audit", "--config", str(config_path), "--output-dir", str(output_dir)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "securebench audit:" in out
    data = json.loads((output_dir / "audit-report.json").read_text())
    assert data["run_id"] == "audit-cli-audit"


def test_cli_audit_self_static_only(tmp_path, capsys):
    exit_code = cli.main(["audit-self", "--output-dir", str(tmp_path), "--static-only"])

    assert exit_code == 0
    assert "run_id=audit-self" in capsys.readouterr().out
    assert (tmp_path / "audit-report.json").exists()


def test_cli_audit_self_reports_docker_requirement(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("securebench.audit.runner.docker_available", lambda: False)

    exit_code = cli.main(["audit-self", "--output-dir", str(tmp_path)])

    assert exit_code == 1
    assert "Docker is required" in capsys.readouterr().out
