from __future__ import annotations

import json
from pathlib import Path

import pytest

from securebench.schemas.benchmark import ProtocolCheck
from securebench.verification.component_contracts import AdapterManifestV2
from securebench.verification.output_artifacts import OutputArtifactCollector


def _check(*artifacts: dict) -> ProtocolCheck:
    return ProtocolCheck.model_validate(
        {
            "id": "behavior",
            "type": "protocol",
            "adapter": "runtime.adapter",
            "protocol": "securebench.example/v1",
            "challenge": {
                "source": "host.challenges",
                "max_cases": 1,
                "max_case_bytes": 1024,
            },
            "output_artifacts": list(artifacts),
            "limits": {
                "seconds_per_case": 2,
                "observation_bytes_per_case": 1024,
            },
        }
    )


def _contract(*artifacts: dict) -> AdapterManifestV2:
    return AdapterManifestV2.model_validate(
        {
            "format": "securebench.adapter/v2",
            "protocol": "securebench.example/v1",
            "command": ["python3", "./adapter.py"],
            "challenge_schema": {"type": "object"},
            "observation_schema": {"type": "object"},
            "evaluation_participants": [
                {"name": "candidate", "type": "candidate", "instances": 1}
            ],
            "output_artifacts": list(artifacts),
            "maximums": {
                "seconds_per_challenge": 2,
                "challenge_bytes": 1024,
                "observation_bytes": 1024,
            },
        },
        strict=False,
    )


def test_collector_passively_parses_bounded_file_and_tree_outputs(tmp_path):
    result = tmp_path / "results" / "result.json"
    result.parent.mkdir()
    result.write_text(json.dumps({"answer": 4}))
    tree = tmp_path / "reports"
    tree.mkdir()
    (tree / "summary.txt").write_text("complete")
    (tree / "latest").symlink_to("summary.txt")
    check = _check(
        {
            "name": "result",
            "parser": "securebench.strict-json/v1",
            "limits": {"max_bytes": 1024},
        },
        {
            "name": "reports",
            "parser": "securebench.tree-manifest/v1",
            "limits": {"max_files": 4, "max_total_bytes": 1024},
        },
    )
    contract = _contract(
        {
            "name": "result",
            "path": "results/result.json",
            "kind": "regular_file",
            "maximum_limits": {"max_bytes": 2048},
        },
        {
            "name": "reports",
            "path": "reports",
            "kind": "directory_tree",
            "maximum_limits": {"max_files": 8, "max_total_bytes": 2048},
        },
    )

    evidence = OutputArtifactCollector().collect(
        tmp_path,
        check,
        contract,
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
    )

    assert evidence[0].status == "observed"
    assert evidence[0].parsed_value == {"answer": 4}
    assert evidence[0].digest.startswith("sha256:")
    assert evidence[0].size == len(result.read_bytes())
    assert evidence[1].status == "observed"
    assert evidence[1].parsed_value == {
        "nodes": [
            {"kind": "symlink", "path": "latest", "target": "summary.txt"},
            {
                "blob": "sha256:eebbf6457e46a7f63acdf9b97390f790ba443d60cfa44b607da7e5c40aa1cc1d",
                "kind": "regular_file",
                "mode": 420,
                "path": "summary.txt",
                "size": 8,
            },
        ]
    }
    assert all(item.challenge_id == "challenge-test" for item in evidence)
    assert all(item.evaluation_id == "evaluation-test" for item in evidence)


@pytest.mark.parametrize(
    ("content", "maximum", "failure_code"),
    [
        (None, 32, "artifact_missing"),
        (b"x" * 33, 32, "artifact_too_large"),
        (b"{duplicate", 32, "invalid_json"),
    ],
)
def test_missing_oversized_and_parser_rejected_outputs_are_candidate_evidence(
    tmp_path,
    content,
    maximum,
    failure_code,
):
    if content is not None:
        target = tmp_path / "result.json"
        target.write_bytes(content)
    check = _check(
        {
            "name": "result",
            "parser": "securebench.strict-json/v1",
            "limits": {"max_bytes": maximum},
        }
    )
    contract = _contract(
        {
            "name": "result",
            "path": "result.json",
            "kind": "regular_file",
            "maximum_limits": {"max_bytes": 64},
        }
    )

    evidence = OutputArtifactCollector().collect(
        tmp_path,
        check,
        contract,
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
    )[0]

    assert evidence.status == "candidate_error"
    assert evidence.failure_code == failure_code
    assert evidence.parsed_value is None
    if failure_code == "invalid_json":
        assert evidence.digest is not None
        assert evidence.size == len(content)
    else:
        assert evidence.digest is None


def test_collector_rejects_parent_symlink_escape_without_reading_outside_evaluation(tmp_path):
    evaluation = tmp_path / "evaluation"
    evaluation.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "result.json").write_text('{"secret": true}')
    (evaluation / "results").symlink_to(outside, target_is_directory=True)
    check = _check(
        {
            "name": "result",
            "parser": "securebench.strict-json/v1",
            "limits": {"max_bytes": 1024},
        }
    )
    contract = _contract(
        {
            "name": "result",
            "path": "results/result.json",
            "kind": "regular_file",
            "maximum_limits": {"max_bytes": 1024},
        }
    )

    evidence = OutputArtifactCollector().collect(
        evaluation,
        check,
        contract,
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
    )[0]

    assert evidence.status == "candidate_error"
    assert evidence.failure_code == "artifact_path_escape"
    assert evidence.digest is None


def test_collector_rejects_parent_symlink_alias_even_when_it_stays_inside_evaluation(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "result.json").write_text('{"aliased": true}')
    (tmp_path / "results").symlink_to("actual", target_is_directory=True)
    check = _check(
        {
            "name": "result",
            "parser": "securebench.strict-json/v1",
            "limits": {"max_bytes": 1024},
        }
    )
    contract = _contract(
        {
            "name": "result",
            "path": "results/result.json",
            "kind": "regular_file",
            "maximum_limits": {"max_bytes": 1024},
        }
    )

    evidence = OutputArtifactCollector().collect(
        tmp_path,
        check,
        contract,
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
    )[0]

    assert evidence.status == "candidate_error"
    assert evidence.failure_code == "artifact_path_escape"


@pytest.mark.parametrize(
    ("create_entry", "failure_code"),
    [
        (lambda root: (root / "escape").symlink_to("../../outside"), "artifact_path_escape"),
        (lambda root: (root / "extra.txt").write_text("too many"), "artifact_too_large"),
    ],
)
def test_tree_outputs_reject_escaping_symlinks_and_entry_overflow(
    tmp_path,
    create_entry,
    failure_code,
):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "one.txt").write_text("one")
    create_entry(reports)
    check = _check(
        {
            "name": "reports",
            "parser": "securebench.tree-manifest/v1",
            "limits": {"max_files": 1, "max_total_bytes": 1024},
        }
    )
    contract = _contract(
        {
            "name": "reports",
            "path": "reports",
            "kind": "directory_tree",
            "maximum_limits": {"max_files": 4, "max_total_bytes": 2048},
        }
    )

    evidence = OutputArtifactCollector().collect(
        tmp_path,
        check,
        contract,
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
    )[0]

    assert evidence.status == "candidate_error"
    assert evidence.failure_code == failure_code
