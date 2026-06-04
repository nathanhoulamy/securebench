from pathlib import Path

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.tester_config import load_tester_config


ROOT = Path(__file__).resolve().parents[1]
SWE_BENCH_VERIFIED_CODEX_SMOKE = ROOT / "benchmarks" / "swe-bench-verified-codex-smoke"
DEEP_SWE_FIRST3 = ROOT / "benchmarks" / "deep-swe-first3"
TERMINAL_TASK_SMOKE = ROOT / "benchmarks" / "terminal-task-smoke"
TERMINAL_BENCH_FIRST10 = ROOT / "benchmarks" / "terminal-bench-first10"


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


def test_deep_swe_first3_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        DEEP_SWE_FIRST3 / "manifest.yaml",
        DEEP_SWE_FIRST3 / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert [row.id for row in rows] == [
        "kombu-single-active-consumer-priority",
        "textual-richlog-follow-state",
        "koota-composite-trait-aspects",
    ]
    assert all(row.family == "repo_patch" for row in rows)
    assert all(row.metadata["source_dataset"] == "datacurve-ai/deep-swe" for row in rows)
    assert all(task.task_type == "repo_patch" for task in tasks)
    assert all(task.metadata["environment"]["workdir"] == "/app" for task in tasks)
    assert all("tests" not in task.agent_payload() for task in tasks)
    assert all("gold_patch" not in task.agent_payload() for task in tasks)
    assert tasks[0].evaluation_payload()["tests"]["test_patch"]["source"] == "inline"


def test_deep_swe_first3_tester_yaml_uses_codex():
    config = load_tester_config(DEEP_SWE_FIRST3 / "tester-codex.yaml")

    assert config.run.id == "deep-swe-first3-codex-gpt-5.4-mini"
    assert config.benchmark.manifest == DEEP_SWE_FIRST3 / "manifest.yaml"
    assert config.benchmark.tasks == DEEP_SWE_FIRST3 / "tasks.jsonl"
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
