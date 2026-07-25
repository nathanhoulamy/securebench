import json
from types import SimpleNamespace

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
  config:
    command:
      - produce
"""
    )

    seen = {}

    def fake_run_tester_config(config, *, limit=None, progress=None, resume=False):
        seen["config"] = config
        seen["limit"] = limit
        seen["progress"] = progress
        seen["resume"] = resume
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
    assert seen["progress"] is not None
    assert seen["resume"] is False
    assert seen["config"].run.output_dir == override_dir
    assert "run_id=cli-tester total=1 verification=complete verified=1 passed=1" in capsys.readouterr().out
    records = [json.loads(line) for line in (override_dir / "candidates.jsonl").read_text().splitlines()]
    assert records == [{"task_id": "task-1"}]


def test_cli_run_reports_config_error(capsys):
    exit_code = cli.main(["run", "--config", "missing.yaml"])

    assert exit_code == 1
    assert "securebench: error:" in capsys.readouterr().out


def test_cli_run_quiet_disables_progress(monkeypatch, tmp_path):
    config_path = tmp_path / "tester.yaml"
    output_dir = tmp_path / "out"
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
  config:
    command: produce
"""
    )
    seen = {}

    def fake_run_tester_config(config, *, limit=None, progress=None, resume=False):
        seen["progress"] = progress
        config.run.output_dir.mkdir(parents=True)
        output_path = config.run.output_dir / "candidates.jsonl"
        output_path.write_text("")
        return FakeTesterSummary(
            run_id=config.run.id,
            total=0,
            verified=0,
            passed=0,
            verification_status="complete",
            output_path=str(output_path),
        )

    monkeypatch.setattr("securebench.cli.run_tester_config", fake_run_tester_config)

    exit_code = cli.main(["run", "--config", str(config_path), "--quiet"])

    assert exit_code == 0
    assert seen["progress"].__class__.__name__ == "NullProgressReporter"


def test_cli_run_passes_resume(monkeypatch, tmp_path):
    config_path = tmp_path / "tester.yaml"
    output_dir = tmp_path / "out"
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
  config:
    command: produce
"""
    )
    seen = {}

    def fake_run_tester_config(config, *, limit=None, progress=None, resume=False):
        seen["resume"] = resume
        config.run.output_dir.mkdir(parents=True)
        output_path = config.run.output_dir / "candidates.jsonl"
        output_path.write_text("")
        return FakeTesterSummary(
            run_id=config.run.id,
            total=0,
            verified=0,
            passed=0,
            verification_status="complete",
            output_path=str(output_path),
        )

    monkeypatch.setattr("securebench.cli.run_tester_config", fake_run_tester_config)

    exit_code = cli.main(["run", "--config", str(config_path), "--resume"])

    assert exit_code == 0
    assert seen["resume"] is True


def test_cli_rejects_unknown_subcommand(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["run-tester", "--config", "tester.yaml"])

    assert exc_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_cli_codex_subscription_login(monkeypatch, tmp_path, capsys):
    auth_path = tmp_path / "auth.json"
    seen = {}

    def fake_login(*, device_auth):
        seen["device_auth"] = device_auth
        return auth_path

    def fake_credentials(path=None):
        seen["path"] = path
        return SimpleNamespace(plan_type="plus")

    monkeypatch.setattr("securebench.cli.run_codex_login", fake_login)
    monkeypatch.setattr(
        "securebench.cli.ensure_valid_codex_oauth_credentials",
        fake_credentials,
    )

    exit_code = cli.main(["auth", "codex", "login", "--device-auth"])

    assert exit_code == 0
    assert seen == {"device_auth": True, "path": auth_path}
    assert "Codex subscription login saved (plus plan)" in capsys.readouterr().out


def test_cli_codex_subscription_status(monkeypatch, capsys):
    monkeypatch.setattr(
        "securebench.cli.ensure_valid_codex_oauth_credentials",
        lambda: SimpleNamespace(plan_type="pro"),
    )

    exit_code = cli.main(["auth", "codex", "status"])

    assert exit_code == 0
    assert "Codex subscription login is ready (pro plan)" in capsys.readouterr().out


def test_cli_codex_subscription_logout(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr("securebench.cli.run_codex_logout", lambda: seen.append("logout"))

    exit_code = cli.main(["auth", "codex", "logout"])

    assert exit_code == 0
    assert seen == ["logout"]
    assert "Codex subscription login removed" in capsys.readouterr().out


class FakeTesterSummary:
    def __init__(self, *, run_id, total, verified, passed, verification_status, output_path):
        self.run_id = run_id
        self.total = total
        self.verified = verified
        self.passed = passed
        self.verification_status = verification_status
        self.output_path = output_path
