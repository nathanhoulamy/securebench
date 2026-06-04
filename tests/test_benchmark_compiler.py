import pytest

from securebench.benchmark_compiler import compile_benchmark_pack, compile_benchmark_row, eval_visibility_for
from securebench.benchmark_pack import (
    AssetDefaults,
    AssetRoots,
    BenchmarkDefaults,
    BenchmarkPack,
    BenchmarkPackManifest,
    BenchmarkRow,
)
from securebench.errors import ConfigError
from securebench.tasks import SecureBenchTask


def manifest():
    return BenchmarkPackManifest(
        id="example-pack",
        version=1,
        defaults=BenchmarkDefaults(family="terminal_task", environment={"image": "python:3.11-slim"}),
        asset_roots=AssetRoots(public="assets/", eval="hidden/"),
        asset_defaults=AssetDefaults(read_only=True),
    )


def test_terminal_task_row_compiles_to_generic_task_with_eval_visibility():
    task = compile_benchmark_row(
        BenchmarkRow(
            id="terminal-1",
            family="terminal_task",
            input={"instructions": "Create output.txt"},
            eval={
                "checker": {"source": "pytest", "path": "checks"},
                "needed_commands": ["chroot"],
                "expected_state": {"file": "output.txt"},
            },
        ),
        manifest=manifest(),
    )

    assert type(task) is SecureBenchTask
    assert task.task_type == "terminal_task"
    assert task.agent_payload() == {"instructions": "Create output.txt"}
    assert task.evaluation_payload()["checker"] == {"source": "pytest", "path": "checks"}
    assert task.evaluation_payload()["needed_commands"] == ["chroot"]
    assert task.hidden_payload()["expected_state"] == {"file": "output.txt"}


def test_repo_patch_row_compiles_tests_as_evaluation_inputs():
    task = compile_benchmark_row(
        BenchmarkRow(
            id="repo-1",
            family="repo_patch",
            input={
                "repo": "example/repo",
                "base_commit": "abc123",
                "instructions": "Fix the bug.",
            },
            eval={
                "tests": {"source": "command", "command": ["pytest", "-q"]},
                "candidate_policy": {"allow_paths": ["src/"]},
                "gold_patch": "diff --git ...",
            },
        ),
        manifest=manifest(),
    )

    assert type(task) is SecureBenchTask
    assert task.task_type == "repo_patch"
    assert "tests" not in task.agent_payload()
    assert "candidate_policy" not in task.agent_payload()
    assert "gold_patch" not in task.agent_payload()
    assert task.evaluation_payload()["tests"] == {"source": "command", "command": ["pytest", "-q"]}
    assert task.evaluation_payload()["candidate_policy"] == {"allow_paths": ["src/"]}
    assert task.hidden_payload()["gold_patch"] == "diff --git ..."


def test_unsupported_family_fails_compilation():
    with pytest.raises(ConfigError, match="Unknown benchmark family"):
        compile_benchmark_row(
            BenchmarkRow(
                id="unsupported-1",
                family="unsupported_family",
                input={"question": "2 + 2?"},
                eval={"answer": 1},
            ),
            manifest=manifest(),
        )


def test_eval_visibility_contains_only_supported_family_fields():
    assert eval_visibility_for("repo_patch", "tests") == "evaluation_inputs"
    assert eval_visibility_for("repo_patch", "gold_patch") == "hidden"
    assert eval_visibility_for("terminal_task", "checker") == "evaluation_inputs"
    assert eval_visibility_for("terminal_task", "expected_state") == "hidden"
    assert eval_visibility_for("unsupported_family", "answer") == "hidden"


def test_compile_benchmark_pack_applies_manifest_defaults(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    tasks_path = tmp_path / "tasks.jsonl"
    manifest_path.write_text(
        """
id: pack
version: 1
defaults:
  family: terminal_task
  environment:
    image: python:3.11-slim
"""
    )
    tasks_path.write_text(
        '{"id":"task-1","input":{"instructions":"Do it"},"eval":{"checker":{"source":"pytest","path":"checks"}}}\n'
    )

    pack = BenchmarkPack(manifest=manifest(), tasks_path=tasks_path)
    tasks = list(compile_benchmark_pack(pack))

    assert len(tasks) == 1
    assert tasks[0].task_type == "terminal_task"
