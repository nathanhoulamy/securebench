import json
from pathlib import Path

from securebench import cli


def test_cli_audit_writes_report(tmp_path, capsys):
    config_path = tmp_path / "tester.yaml"
    output_dir = tmp_path / "audit"
    root = Path.cwd()
    config_path.write_text(
        f"""
schema_version: "1.0"
run:
  id: audit-cli
  output_dir: {tmp_path / "run"}
benchmark:
  manifest: {root / "benchmarks/terminal-bench/manifest-v2.yaml"}
  tasks: {root / "benchmarks/terminal-bench/tasks-v2.jsonl"}
harness:
  type: command
  config:
    command: "true"
"""
    )

    exit_code = cli.main(["audit", "--config", str(config_path), "--output-dir", str(output_dir)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "securebench audit:" in out
    data = json.loads((output_dir / "audit-report.json").read_text())
    assert data["run_id"] == "audit-cli-audit"


def test_cli_audit_self(tmp_path, capsys):
    exit_code = cli.main(["audit-self", "--output-dir", str(tmp_path)])

    assert exit_code == 0
    assert "run_id=audit-self" in capsys.readouterr().out
    assert (tmp_path / "audit-report.json").exists()


def test_cli_audit_self_is_static_and_does_not_require_docker(tmp_path, capsys):
    exit_code = cli.main(["audit-self", "--output-dir", str(tmp_path)])

    assert exit_code == 0
    assert "run_id=audit-self" in capsys.readouterr().out
