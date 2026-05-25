from pathlib import Path

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.tester_config import load_tester_config


ROOT = Path(__file__).resolve().parents[1]
CODE_COMPLETION_SMOKE = ROOT / "benchmarks" / "code-completion-smoke"
HUMANEVAL_MINI = ROOT / "benchmarks" / "humaneval-mini"
MMLU_ABSTRACT_ALGEBRA_MINI = ROOT / "benchmarks" / "mmlu-abstract-algebra-mini"
SQUAD_V1_MINI = ROOT / "benchmarks" / "squad-v1-mini"
SWE_BENCH_VERIFIED_CODEX_SMOKE = ROOT / "benchmarks" / "swe-bench-verified-codex-smoke"
TERMINAL_TASK_SMOKE = ROOT / "benchmarks" / "terminal-task-smoke"
TERMINAL_BENCH_FIRST10 = ROOT / "benchmarks" / "terminal-bench-first10"
TRUTHFULQA_GENERATION_MINI = ROOT / "benchmarks" / "truthfulqa-generation-mini"


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
    assert config.harness.config["model"] == "gpt-5.4-mini"


def test_humaneval_mini_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        HUMANEVAL_MINI / "manifest.yaml",
        HUMANEVAL_MINI / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert len(rows) == 10
    assert all(row.family == "code_completion" for row in rows)
    assert all(row.metadata["source_dataset"] == "openai/human-eval" for row in rows)
    assert all(task.task_type == "code_completion" for task in tasks)
    assert all(task.metadata["environment"]["image"] == "python:3.11-slim" for task in tasks)


def test_humaneval_mini_tester_yaml_uses_codex():
    config = load_tester_config(HUMANEVAL_MINI / "tester-codex.yaml")

    assert config.run.id == "humaneval-mini-codex-gpt-5.4-mini"
    assert config.benchmark.manifest == HUMANEVAL_MINI / "manifest.yaml"
    assert config.benchmark.tasks == HUMANEVAL_MINI / "tasks.jsonl"
    assert config.harness.type == "codex"
    assert config.harness.config["model"] == "gpt-5.4-mini"


def test_mmlu_abstract_algebra_mini_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        MMLU_ABSTRACT_ALGEBRA_MINI / "manifest.yaml",
        MMLU_ABSTRACT_ALGEBRA_MINI / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert len(rows) == 10
    assert all(row.family == "multiple_choice" for row in rows)
    assert all(row.metadata["source_dataset"] == "hendrycks/MMLU" for row in rows)
    assert all(task.task_type == "multiple_choice" for task in tasks)
    assert all(task.metadata["environment"]["image"] == "python:3.11-slim" for task in tasks)


def test_mmlu_abstract_algebra_mini_tester_yaml_uses_codex():
    config = load_tester_config(MMLU_ABSTRACT_ALGEBRA_MINI / "tester-codex.yaml")

    assert config.run.id == "mmlu-abstract-algebra-mini-codex-gpt-5.4-mini"
    assert config.benchmark.manifest == MMLU_ABSTRACT_ALGEBRA_MINI / "manifest.yaml"
    assert config.benchmark.tasks == MMLU_ABSTRACT_ALGEBRA_MINI / "tasks.jsonl"
    assert config.harness.type == "codex"
    assert config.harness.config["model"] == "gpt-5.4-mini"


def test_squad_v1_mini_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        SQUAD_V1_MINI / "manifest.yaml",
        SQUAD_V1_MINI / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert len(rows) == 10
    assert all(row.family == "short_answer" for row in rows)
    assert all(row.metadata["source_dataset"] == "SQuAD v1.1" for row in rows)
    assert all(task.task_type == "short_answer" for task in tasks)
    assert all(task.metadata["environment"]["image"] == "python:3.11-slim" for task in tasks)


def test_squad_v1_mini_tester_yaml_uses_codex():
    config = load_tester_config(SQUAD_V1_MINI / "tester-codex.yaml")

    assert config.run.id == "squad-v1-mini-codex-gpt-5.4-mini"
    assert config.benchmark.manifest == SQUAD_V1_MINI / "manifest.yaml"
    assert config.benchmark.tasks == SQUAD_V1_MINI / "tasks.jsonl"
    assert config.harness.type == "codex"
    assert config.harness.config["model"] == "gpt-5.4-mini"


def test_truthfulqa_generation_mini_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        TRUTHFULQA_GENERATION_MINI / "manifest.yaml",
        TRUTHFULQA_GENERATION_MINI / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert len(rows) == 10
    assert all(row.family == "free_response" for row in rows)
    assert all(row.metadata["source_dataset"] == "TruthfulQA generation" for row in rows)
    assert all(task.task_type == "free_response" for task in tasks)
    assert all(task.metadata["environment"]["image"] == "python:3.11-slim" for task in tasks)


def test_truthfulqa_generation_mini_tester_yaml_uses_codex():
    config = load_tester_config(TRUTHFULQA_GENERATION_MINI / "tester-codex.yaml")

    assert config.run.id == "truthfulqa-generation-mini-codex-gpt-5.4-mini"
    assert config.benchmark.manifest == TRUTHFULQA_GENERATION_MINI / "manifest.yaml"
    assert config.benchmark.tasks == TRUTHFULQA_GENERATION_MINI / "tasks.jsonl"
    assert config.harness.type == "codex"
    assert config.harness.config["model"] == "gpt-5.4-mini"


def test_swe_bench_verified_codex_smoke_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        SWE_BENCH_VERIFIED_CODEX_SMOKE / "manifest.yaml",
        SWE_BENCH_VERIFIED_CODEX_SMOKE / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert len(rows) == 10
    assert rows[0].id == "astropy__astropy-12907"
    assert rows[-1].id == "scikit-learn__scikit-learn-26323"
    assert all(row.family == "repo_patch" for row in rows)
    assert all(task.task_type == "repo_patch" for task in tasks)
    assert all(task.metadata["environment"]["workdir"] == "/testbed" for task in tasks)


def test_swe_bench_verified_codex_smoke_tester_yaml_uses_codex():
    config = load_tester_config(SWE_BENCH_VERIFIED_CODEX_SMOKE / "tester-codex.yaml")

    assert config.run.id == "swe-bench-verified-codex-smoke-gpt-5.4-mini"
    assert config.benchmark.manifest == SWE_BENCH_VERIFIED_CODEX_SMOKE / "manifest.yaml"
    assert config.benchmark.tasks == SWE_BENCH_VERIFIED_CODEX_SMOKE / "tasks.jsonl"
    assert config.harness.type == "codex"
    assert config.harness.config["model"] == "gpt-5.4-mini"


def test_terminal_task_smoke_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        TERMINAL_TASK_SMOKE / "manifest.yaml",
        TERMINAL_TASK_SMOKE / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert [row.id for row in rows] == ["terminal-task-smoke/create-output-file"]
    assert all(row.family == "terminal_task" for row in rows)
    assert all(task.task_type == "terminal_task" for task in tasks)
    assert tasks[0].agent_payload() == {
        "instructions": "Create a file named output.txt in the workspace. Its contents must be exactly: securebench terminal task\n"
    }
    assert "checker" not in tasks[0].agent_payload()
    assert "expected_state" not in tasks[0].agent_payload()


def test_terminal_task_smoke_tester_yaml_uses_command_harness():
    config = load_tester_config(TERMINAL_TASK_SMOKE / "tester-command.yaml")

    assert config.run.id == "terminal-task-smoke-command"
    assert config.benchmark.manifest == TERMINAL_TASK_SMOKE / "manifest.yaml"
    assert config.benchmark.tasks == TERMINAL_TASK_SMOKE / "tasks.jsonl"
    assert config.harness.type == "command"


def test_terminal_bench_first10_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        TERMINAL_BENCH_FIRST10 / "manifest.yaml",
        TERMINAL_BENCH_FIRST10 / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert len(rows) == 10
    assert rows[0].id == "terminal-bench-first10/path-tracing"
    assert rows[-1].id == "terminal-bench-first10/stable-parallel-kmeans"
    assert all(row.family == "terminal_task" for row in rows)
    assert all(task.task_type == "terminal_task" for task in tasks)
    assert all("checker" not in task.agent_payload() for task in tasks)
    assert any(
        task.metadata["environment"].get("materialize_workdir_from_image") is True
        for task in tasks
    )


def test_terminal_bench_first10_tester_yaml_uses_codex_harness():
    config = load_tester_config(TERMINAL_BENCH_FIRST10 / "tester-codex.yaml")

    assert config.run.id == "terminal-bench-first10-codex-gpt-5.4-mini"
    assert config.benchmark.manifest == TERMINAL_BENCH_FIRST10 / "manifest.yaml"
    assert config.benchmark.tasks == TERMINAL_BENCH_FIRST10 / "tasks.jsonl"
    assert config.harness.type == "codex"
    assert config.harness.config["model"] == "gpt-5.4-mini"
