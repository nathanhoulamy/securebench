from pathlib import Path

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.tester_config import load_tester_config


ROOT = Path(__file__).resolve().parents[1]
CODE_COMPLETION_SMOKE = ROOT / "benchmarks" / "code-completion-smoke"
MULTIPLE_CHOICE_SMOKE = ROOT / "benchmarks" / "multiple-choice-smoke"


def test_code_completion_smoke_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        CODE_COMPLETION_SMOKE / "manifest.yaml",
        CODE_COMPLETION_SMOKE / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert [row.id for row in rows] == [
        "code-completion-smoke/add_numbers",
        "code-completion-smoke/normalize_slug",
        "code-completion-smoke/windowed",
    ]
    assert all(row.family == "code_completion" for row in rows)
    assert all(row.environment["image"] == "node:22-bookworm" for row in rows)
    assert all(task.task_type == "code_completion" for task in tasks)
    assert all("tests" not in task.agent_payload() for task in tasks)
    assert all("canonical_solution" not in task.agent_payload() for task in tasks)
    assert all("starter_code" in task.agent_payload() for task in tasks)
    assert all(task.metadata["environment"]["image"] == "node:22-bookworm" for task in tasks)


def test_code_completion_smoke_tester_yaml_loads():
    config = load_tester_config(CODE_COMPLETION_SMOKE / "tester-codex.yaml")

    assert config.run.id == "code-completion-smoke-codex"
    assert config.benchmark.manifest == CODE_COMPLETION_SMOKE / "manifest.yaml"
    assert config.benchmark.tasks == CODE_COMPLETION_SMOKE / "tasks.jsonl"
    assert config.harness.type == "codex"
    assert config.harness.mode == "mounted"
    assert config.harness.config["model"] == "gpt-5.4-mini"


def test_multiple_choice_smoke_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        MULTIPLE_CHOICE_SMOKE / "manifest.yaml",
        MULTIPLE_CHOICE_SMOKE / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert [row.id for row in rows] == [
        "multiple-choice-smoke/arithmetic",
        "multiple-choice-smoke/protocol",
        "multiple-choice-smoke/hash",
    ]
    assert all(row.family == "multiple_choice" for row in rows)
    assert all(task.task_type == "multiple_choice" for task in tasks)
    assert all("answer" not in task.agent_payload() for task in tasks)
    assert all("choices" in task.agent_payload() for task in tasks)


def test_multiple_choice_smoke_tester_yaml_loads():
    config = load_tester_config(MULTIPLE_CHOICE_SMOKE / "tester-command.yaml")

    assert config.run.id == "multiple-choice-smoke-command"
    assert config.benchmark.manifest == MULTIPLE_CHOICE_SMOKE / "manifest.yaml"
    assert config.benchmark.tasks == MULTIPLE_CHOICE_SMOKE / "tasks.jsonl"
    assert config.harness.type == "command"
    assert config.harness.mode == "host"
