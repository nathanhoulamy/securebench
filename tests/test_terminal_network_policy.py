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
        # The bare python image ships no numpy/scipy, so the fitting stack must
        # be installable; nothing else is reachable.
        "terminal-bench/raman-fitting": ("pypi.org", "pythonhosted.org"),
        # The public task explicitly directs the agent to the RCSB PDB and
        # FPbase APIs.
        "terminal-bench/protein-assembly": (
            "rcsb.org",
            "fpbase.org",
            "pypi.org",
            "pythonhosted.org",
        ),
        "terminal-bench/mteb-leaderboard": (
            "huggingface.co",
            "hf.co",
            "pypi.org",
            "pythonhosted.org",
        ),
        "terminal-bench/mteb-retrieve": (
            "huggingface.co",
            "hf.co",
            "xethub.hf.co",
            "pypi.org",
            "pythonhosted.org",
        ),
        # The task requires installing PyStan 3.10.0.
        "terminal-bench/rstan-to-pystan": ("pypi.org", "pythonhosted.org"),
    }

    # Rows converted before the agent-network work all declare the legacy
    # `internet` mode, which grants no destinations under the default benchmark
    # policy. Rows converted afterwards declare the narrowest policy the public
    # task actually needs, so the mode is asserted per row rather than assumed.
    narrow_modes = {
        "terminal-bench/password-recovery": "none",
        "terminal-bench/log-summary-date-ranges": "none",
        "terminal-bench/raman-fitting": "restricted",
        "terminal-bench/protein-assembly": "restricted",
        "terminal-bench/write-compressor": "none",
        "terminal-bench/mteb-leaderboard": "restricted",
        "terminal-bench/mteb-retrieve": "restricted",
        "terminal-bench/rstan-to-pystan": "restricted",
    }

    # Derived from the pack so adding a row does not break this test; what is
    # asserted is that every row's declared policy matches the table above.
    assert len(tasks) == len(list(pack.load_rows()))
    for task in tasks.values():
        assert task.environment.agent_network.mode == narrow_modes.get(
            task.id, "internet"
        ), task.id
        assert task_allowed_domains(task, NetworkPolicy()) == expected.get(task.id, ()), (
            task.id
        )
