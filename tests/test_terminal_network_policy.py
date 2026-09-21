from pathlib import Path

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.harnesses.shared import task_allowed_domains
from securebench.network_policy import NetworkPolicy


ROOT = Path(__file__).resolve().parents[1]


def test_terminal_rows_use_declared_domains_with_benchmark_default_policy():
    pack_root = ROOT / "benchmarks" / "terminal-bench"
    pack = load_benchmark_pack(pack_root / "manifest-v2.yaml", pack_root / "tasks-v2.jsonl")
    tasks = {task.id: task for task in compile_benchmark_pack(pack)}

    expected = {
        "terminal-bench/cancel-async-tasks": ("pypi.org", "pythonhosted.org"),
        "terminal-bench/count-dataset-tokens": (
            "huggingface.co",
            "hf.co",
            "xethub.hf.co",
            "pypi.org",
            "pythonhosted.org",
        ),
        "terminal-bench/extract-moves-from-video": (
            "youtube.com",
            "googlevideo.com",
            "ytimg.com",
            "pypi.org",
            "pythonhosted.org",
        ),
        "terminal-bench/headless-terminal": ("pypi.org", "pythonhosted.org"),
        "terminal-bench/hf-model-inference": (
            "huggingface.co",
            "hf.co",
            "xethub.hf.co",
            "pypi.org",
            "pythonhosted.org",
        ),
        "terminal-bench/install-windows-3.11": ("download.qemu.org",),
        "terminal-bench/kv-store-grpc": ("pypi.org", "pythonhosted.org"),
    }

    assert len(tasks) == 28
    for task in tasks.values():
        assert task.environment.agent_network.mode == "internet"
        assert task_allowed_domains(task, NetworkPolicy()) == expected.get(task.id, ())
