import json
from pathlib import Path

from securebench.config import parse_run_config
from securebench.datasets import DatasetRow
from securebench.run import result_to_record, run_config


def make_config(output_path: Path, *, limit=2):
    return parse_run_config(
        {
            "schema_version": "0.1",
            "run": {
                "id": "mmlu-static-test",
                "limit": limit,
                "output_path": str(output_path),
            },
            "dataset": {
                "provider": "huggingface",
                "name": "cais/mmlu",
                "config": "abstract_algebra",
                "split": "test",
                "streaming": True,
            },
            "adapter": {
                "id": "mmlu",
            },
            "producer": {
                "kind": "static",
                "config": {
                    "text": "A",
                },
            },
            "runner": {
                "type": "multiple_choice",
            },
        }
    )


def make_rows():
    return [
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
                "choices": ["wrong", "correct"],
                "answer": 1,
                "subject": "test",
            },
            context={"config": "abstract_algebra", "split": "test", "row_idx": 1},
        ),
    ]


def test_run_config_evaluates_rows_and_writes_jsonl(tmp_path):
    output_path = tmp_path / "runs" / "results.jsonl"

    summary = run_config(make_config(output_path), rows=make_rows())

    assert summary.run_id == "mmlu-static-test"
    assert summary.total == 2
    assert summary.passed == 1
    assert summary.accuracy == 0.5
    records = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert records[0]["run_id"] == "mmlu-static-test"
    assert records[0]["task_id"] == "mmlu/abstract_algebra/test/0"
    assert records[0]["task_type"] == "multiple_choice"
    assert records[0]["passed"] is True
    assert records[0]["candidate_text"] == "A"
    assert records[1]["passed"] is False


def test_run_config_applies_limit_to_injected_rows(tmp_path):
    summary = run_config(make_config(tmp_path / "results.jsonl", limit=1), rows=make_rows())

    assert summary.total == 1


def test_result_to_record_includes_runner_and_producer_metadata(tmp_path):
    output_path = tmp_path / "results.jsonl"
    run_config(make_config(output_path, limit=1), rows=make_rows())
    record = json.loads(output_path.read_text().splitlines()[0])

    assert "producer_metadata" in record
    assert record["runner_metadata"] == {
        "expected_answer": "A",
        "parsed_answer": "A",
    }
