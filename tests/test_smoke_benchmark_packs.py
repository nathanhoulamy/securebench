from pathlib import Path

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.tester_config import load_tester_config


ROOT = Path(__file__).resolve().parents[1]
SWE_BENCH_VERIFIED = ROOT / "benchmarks" / "swe-bench-verified"
SWE_BENCH_PRO = ROOT / "benchmarks" / "swe-bench-pro"
DEEP_SWE = ROOT / "benchmarks" / "deep-swe"
TERMINAL_BENCH = ROOT / "benchmarks" / "terminal-bench"


def test_swe_bench_verified_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        SWE_BENCH_VERIFIED / "manifest.yaml",
        SWE_BENCH_VERIFIED / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert len(rows) == 500
    assert rows[0].id == "astropy__astropy-12907"
    assert rows[-1].id == "sympy__sympy-24661"
    assert all(row.family == "repo_patch" for row in rows)
    assert all(row.metadata["source_dataset"] == "SWE-bench/SWE-bench_Verified" for row in rows)
    assert all(task.task_type == "repo_patch" for task in tasks)
    assert all(task.metadata["environment"]["workdir"] == "/testbed" for task in tasks)


def test_swe_bench_verified_tester_yaml_uses_codex():
    config = load_tester_config(SWE_BENCH_VERIFIED / "tester-codex.yaml")

    assert config.run.id == "swe-bench-verified-codex-gpt-5.4-mini"
    assert config.benchmark.manifest == SWE_BENCH_VERIFIED / "manifest.yaml"
    assert config.benchmark.tasks == SWE_BENCH_VERIFIED / "tasks.jsonl"
    assert config.harness.type == "codex"
    assert config.harness.config["model"] == "gpt-5.4-mini"
    assert config.harness.config["allow_external_tools"] is False
    assert config.verification.allow_network is False


def test_swe_bench_pro_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        SWE_BENCH_PRO / "manifest.yaml",
        SWE_BENCH_PRO / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert len(rows) == 731
    assert rows[0].id == "instance_NodeBB__NodeBB-04998908ba6721d64eba79ae3b65a351dcfbc5b5-vnan"
    assert rows[-1].id == (
        "instance_gravitational__teleport-82185f232ae8974258397e121b3bc2ed0c3729ed-"
        "v626ec2a48416b10a88641359a169d99e935ff037"
    )
    assert len({row.id for row in rows}) == 731
    assert all(row.family == "repo_patch" for row in rows)
    assert all(row.metadata["source_dataset"] == "ScaleAI/SWE-bench_Pro" for row in rows)
    assert all(task.task_type == "repo_patch" for task in tasks)
    assert all(task.metadata["environment"]["workdir"] == "/app" for task in tasks)
    assert all("tests" not in task.agent_payload() for task in tasks)
    assert all("gold_patch" not in task.agent_payload() for task in tasks)
    assert all(
        task.evaluation_payload()["tests"]["test_patch"]["source"] == "inline"
        for task in tasks
    )


def test_swe_bench_pro_tester_yaml_uses_codex_and_networked_verification():
    config = load_tester_config(SWE_BENCH_PRO / "tester-codex.yaml")

    assert config.run.id == "swe-bench-pro-codex-gpt-5.4-mini"
    assert config.run.max_workers == 2
    assert config.benchmark.manifest == SWE_BENCH_PRO / "manifest.yaml"
    assert config.benchmark.tasks == SWE_BENCH_PRO / "tasks.jsonl"
    assert config.harness.type == "codex"
    assert config.harness.config["model"] == "gpt-5.4-mini"
    assert config.harness.config["allow_external_tools"] is False
    assert config.verification.allow_network is True
    assert config.docker.max_cached_images == 2


def test_deep_swe_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        DEEP_SWE / "manifest.yaml",
        DEEP_SWE / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert [row.id for row in rows] == [
        "fastapi-implicit-head-options",
        "kea-atomic-signal-selectors",
        "testem-bail-on-test-failure",
        "httpx-streaming-json-iteration",
        "anko-default-function-arguments",
    ]
    assert all(row.family == "repo_patch" for row in rows)
    assert all(row.metadata["source_dataset"] == "datacurve-ai/deep-swe" for row in rows)
    assert all(task.task_type == "repo_patch" for task in tasks)
    assert all(task.metadata["environment"]["workdir"] == "/app" for task in tasks)
    assert all("tests" not in task.agent_payload() for task in tasks)
    assert all("gold_patch" not in task.agent_payload() for task in tasks)
    assert tasks[0].evaluation_payload()["tests"]["test_patch"]["source"] == "inline"


def test_deep_swe_tester_yaml_uses_codex():
    config = load_tester_config(DEEP_SWE / "tester-codex.yaml")

    assert config.run.id == "deep-swe-codex-gpt-5.4-mini"
    assert config.benchmark.manifest == DEEP_SWE / "manifest.yaml"
    assert config.benchmark.tasks == DEEP_SWE / "tasks.jsonl"
    assert config.harness.type == "codex"
    assert config.harness.config["model"] == "gpt-5.4-mini"
    assert config.harness.config["allow_external_tools"] is False
    assert config.verification.allow_network is False


def test_terminal_bench_pack_loads_and_compiles():
    pack = load_benchmark_pack(
        TERMINAL_BENCH / "manifest.yaml",
        TERMINAL_BENCH / "tasks.jsonl",
    )

    rows = pack.load_rows()
    tasks = list(compile_benchmark_pack(pack))

    assert len(rows) == 89
    assert rows[0].id == "terminal-bench/path-tracing"
    assert rows[-1].id == "terminal-bench/financial-document-processor"
    assert all(row.family == "terminal_task" for row in rows)
    assert all(row.metadata["source_dataset"] == "Terminal-Bench 2.0" for row in rows)
    assert all(task.task_type == "terminal_task" for task in tasks)
    assert all("checker" not in task.agent_payload() for task in tasks)
    assert all(
        task.metadata["environment"].get("materialize_workdir_from_image") is True
        for task in tasks
    )


def test_terminal_bench_tester_yaml_uses_codex_harness():
    config = load_tester_config(TERMINAL_BENCH / "tester-codex.yaml")

    assert config.run.id == "terminal-bench-codex-gpt-5.4-mini"
    assert config.benchmark.manifest == TERMINAL_BENCH / "manifest.yaml"
    assert config.benchmark.tasks == TERMINAL_BENCH / "tasks.jsonl"
    assert config.harness.type == "codex"
    assert config.harness.config["model"] == "gpt-5.4-mini"
    assert config.harness.config["allow_external_tools"] is False
    assert config.verification.allow_network is True
