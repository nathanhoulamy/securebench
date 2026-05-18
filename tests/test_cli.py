import json

import pytest

from securebench import cli


def test_cli_run_loads_tester_config_applies_overrides_and_prints_summary(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "tester.yaml"
    output_dir = tmp_path / "out"
    override_dir = tmp_path / "override"
    manifest_path = tmp_path / "manifest.yaml"
    tasks_path = tmp_path / "tasks.jsonl"
    config_path.write_text(
        f"""
schema_version: "0.2"
run:
  id: cli-tester
  output_dir: {output_dir}
benchmark:
  manifest: {manifest_path}
  tasks: {tasks_path}
harness:
  type: command
  mode: host
  config:
    command:
      - produce
"""
    )

    seen = {}

    def fake_run_tester_config(config, *, limit=None):
        seen["config"] = config
        seen["limit"] = limit
        config.run.output_dir.mkdir(parents=True)
        output_path = config.run.output_dir / "candidates.jsonl"
        output_path.write_text(json.dumps({"task_id": "task-1"}) + "\n")
        return FakeTesterSummary(
            run_id=config.run.id,
            total=1,
            verified=1,
            passed=1,
            verification_status="complete",
            output_path=str(output_path),
        )

    monkeypatch.setattr("securebench.cli.run_tester_config", fake_run_tester_config)

    exit_code = cli.main(
        [
            "run",
            "--config",
            str(config_path),
            "--limit",
            "1",
            "--output-dir",
            str(override_dir),
        ]
    )

    assert exit_code == 0
    assert seen["limit"] == 1
    assert seen["config"].run.output_dir == override_dir
    assert "run_id=cli-tester total=1 verification=complete verified=1 passed=1" in capsys.readouterr().out
    records = [json.loads(line) for line in (override_dir / "candidates.jsonl").read_text().splitlines()]
    assert records == [{"task_id": "task-1"}]


def test_cli_run_reports_config_error(capsys):
    exit_code = cli.main(["run", "--config", "missing.yaml"])

    assert exit_code == 1
    assert "securebench: error:" in capsys.readouterr().out


def test_cli_has_no_legacy_run_tester_subcommand(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["run-tester", "--config", "tester.yaml"])

    assert exc_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


class FakeTesterSummary:
    def __init__(self, *, run_id, total, verified, passed, verification_status, output_path):
        self.run_id = run_id
        self.total = total
        self.verified = verified
        self.passed = passed
        self.verification_status = verification_status
        self.output_path = output_path
