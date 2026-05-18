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
from securebench.tasks import CodeCompletionTask, MultipleChoiceTask, SecureBenchTask


def manifest():
    return BenchmarkPackManifest(
        id="example-pack",
        version=1,
        defaults=BenchmarkDefaults(family="terminal_task", environment={"image": "python:3.11-slim"}),
        asset_roots=AssetRoots(public="assets/", eval="hidden/"),
        asset_defaults=AssetDefaults(read_only=True),
    )


def test_multiple_choice_row_compiles_to_specialized_task():
    task = compile_benchmark_row(
        BenchmarkRow(
            id="mc-1",
            family="multiple_choice",
            input={
                "question": "2 + 2?",
                "choices": ["1", "2", "4", "5"],
            },
            eval={
                "answer": 2,
            },
        ),
        manifest=manifest(),
    )

    assert isinstance(task, MultipleChoiceTask)
    assert task.benchmark_id == "example-pack"
    assert task.task_type == "multiple_choice"
    assert task.agent_payload() == {
        "question": "2 + 2?",
        "choices": ["1", "2", "4", "5"],
    }
    assert task.hidden_payload()["answer"] == 2


def test_code_completion_row_compiles_tests_as_evaluation_inputs():
    task = compile_benchmark_row(
        BenchmarkRow(
            id="code-1",
            family="code_completion",
            input={
                "prompt": "def add(a, b):\n",
                "language": "python",
            },
            eval={
                "tests": {"source": "inline", "code": "def check(candidate): assert candidate(2, 3) == 5"},
                "canonical_solution": "    return a + b",
            },
        ),
        manifest=manifest(),
    )

    assert isinstance(task, CodeCompletionTask)
    assert "tests" not in task.agent_payload()
    assert "canonical_solution" not in task.agent_payload()
    assert task.evaluation_payload()["tests"] == {
        "source": "inline",
        "code": "def check(candidate): assert candidate(2, 3) == 5",
    }
    assert task.hidden_payload()["canonical_solution"] == "    return a + b"
    assert {resource.name for resource in task.resources.by_visibility("evaluation_inputs")} == {"tests"}


def test_terminal_task_row_compiles_to_generic_task_with_eval_visibility():
    task = compile_benchmark_row(
        BenchmarkRow(
            id="terminal-1",
            family="terminal_task",
            input={"instructions": "Create output.txt"},
            eval={
                "checker": {"command": "python checks/check.py"},
                "expected_state": {"file": "output.txt"},
            },
        ),
        manifest=manifest(),
    )

    assert type(task) is SecureBenchTask
    assert task.task_type == "terminal_task"
    assert task.agent_payload() == {"instructions": "Create output.txt"}
    assert task.evaluation_payload()["checker"] == {"command": "python checks/check.py"}
    assert task.hidden_payload()["expected_state"] == {"file": "output.txt"}


def test_assets_are_public_when_non_empty():
    task = compile_benchmark_row(
        BenchmarkRow(
            id="asset-1",
            family="terminal_task",
            input={"instructions": "Read the file"},
            assets=({"path": "auth.log", "mount": "auth.log"},),
        ),
        manifest=manifest(),
    )

    assert task.agent_payload()["assets"] == [{"path": "auth.log", "mount": "auth.log"}]
    assert task.resources.resources["assets"].visibility == "public"


def test_environment_and_pack_details_are_metadata_not_agent_payload():
    row = BenchmarkRow(
        id="meta-1",
        family="terminal_task",
        input={"instructions": "Do it"},
        environment={"image": "python:3.12-slim", "timeout_seconds": 30},
        metadata={"difficulty": "easy"},
    )

    task = compile_benchmark_row(row, manifest=manifest())

    assert task.metadata["difficulty"] == "easy"
    assert task.metadata["benchmark_pack"] == {
        "id": "example-pack",
        "version": 1,
        "manifest_path": None,
    }
    assert task.metadata["environment"] == {"image": "python:3.12-slim", "timeout_seconds": 30}
    assert task.metadata["asset_roots"] == {"public": "assets/", "eval": "hidden/"}
    assert task.metadata["asset_defaults"] == {"read_only": True}
    assert "environment" not in task.agent_payload()
    assert "asset_roots" not in task.agent_payload()
    assert "asset_defaults" not in task.agent_payload()


def test_unknown_family_defaults_eval_fields_to_hidden():
    task = compile_benchmark_row(
        BenchmarkRow(
            id="custom-1",
            family="custom_family",
            input={"prompt": "Solve this"},
            eval={"private_key": "secret"},
        ),
        manifest=manifest(),
    )

    assert type(task) is SecureBenchTask
    assert task.task_type == "custom_family"
    assert task.agent_payload() == {"prompt": "Solve this"}
    assert task.evaluation_payload() == {"prompt": "Solve this"}
    assert task.hidden_payload()["private_key"] == "secret"


def test_unknown_eval_key_in_known_family_defaults_to_hidden():
    task = compile_benchmark_row(
        BenchmarkRow(
            id="terminal-unknown-eval",
            family="terminal_task",
            input={"instructions": "Do it"},
            eval={"secret_rubric": "private"},
        ),
        manifest=manifest(),
    )

    assert task.hidden_payload()["secret_rubric"] == "private"
    assert "secret_rubric" not in task.evaluation_payload()


@pytest.mark.parametrize(
    "row",
    [
        BenchmarkRow(id="collision-1", family="terminal_task", input={"assets": "bad"}, assets=({"path": "x"},)),
        BenchmarkRow(id="collision-2", family="terminal_task", input={"checker": "public"}, eval={"checker": "private"}),
        BenchmarkRow(id="collision-3", family="terminal_task", assets=({"path": "x"},), eval={"assets": "private"}),
    ],
)
def test_resource_name_collisions_are_rejected(row):
    with pytest.raises(ConfigError, match="Duplicate compiled resource name"):
        compile_benchmark_row(row, manifest=manifest())


def test_eval_visibility_registry_defaults_to_hidden():
    assert eval_visibility_for("terminal_task", "checker") == "evaluation_inputs"
    assert eval_visibility_for("terminal_task", "unknown") == "hidden"
    assert eval_visibility_for("unknown", "checker") == "hidden"


def test_compile_benchmark_pack_iterates_rows(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    tasks_path = tmp_path / "tasks.jsonl"
    manifest_path.write_text("id: example-pack\nversion: 1\ndefaults:\n  family: terminal_task\n")
    tasks_path.write_text('{"id":"task-1","input":{"instructions":"one"}}\n{"id":"task-2","input":{"instructions":"two"}}\n')
    pack = BenchmarkPack(manifest=manifest(), tasks_path=tasks_path)

    tasks = list(compile_benchmark_pack(pack, limit=1))

    assert [task.id for task in tasks] == ["task-1"]
