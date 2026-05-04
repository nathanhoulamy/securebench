import json
from pathlib import Path

from securebench import cli
from securebench.datasets import DatasetRow


def test_cli_run_loads_config_applies_overrides_and_prints_summary(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    output_path = tmp_path / "results.jsonl"
    config_path.write_text(
        f"""
schema_version: "0.1"
run:
  id: cli-test
  limit: 5
  output_path: {tmp_path / "ignored.jsonl"}
dataset:
  provider: huggingface
  name: cais/mmlu
  config: abstract_algebra
  split: test
adapter:
  id: mmlu
producer:
  type: static
  config:
    text: A
runner:
  type: multiple_choice
"""
    )

    rows = [
        DatasetRow(
            row={
                "question": "first?",
                "choices": ["correct", "wrong"],
                "answer": 0,
                "subject": "test",
            },
            context={"config": "abstract_algebra", "split": "test", "row_idx": 0},
        ),
        DatasetRow(
            row={
                "question": "second?",
                "choices": ["correct", "wrong"],
                "answer": 0,
                "subject": "test",
            },
            context={"config": "abstract_algebra", "split": "test", "row_idx": 1},
        ),
    ]

    monkeypatch.setattr("securebench.run.RunConfig.dataset_ref", lambda self: FakeDatasetRef(rows))

    exit_code = cli.main(
        [
            "run",
            "--config",
            str(config_path),
            "--limit",
            "1",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert "run_id=cli-test total=1 passed=1" in capsys.readouterr().out
    records = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert len(records) == 1


def test_cli_run_reports_config_error(capsys):
    exit_code = cli.main(["run", "--config", "missing.yaml"])

    assert exit_code == 1
    assert "securebench: error:" in capsys.readouterr().out


class FakeDatasetRef:
    def __init__(self, rows):
        self.rows = rows

    def iter_rows(self, *, limit=None):
        for index, row in enumerate(self.rows):
            if limit is not None and index >= limit:
                break
            yield row
