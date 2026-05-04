"""Registry for built-in benchmark adapters."""

from __future__ import annotations

from collections.abc import Callable

from securebench.adapters.base import BenchmarkAdapter
from securebench.adapters.humaneval import HumanEvalAdapter
from securebench.adapters.mmlu import MMLUAdapter
from securebench.adapters.swebench import SWEBenchVerifiedAdapter


_ADAPTER_FACTORIES: dict[str, Callable[[], BenchmarkAdapter]] = {
    MMLUAdapter.benchmark_id: MMLUAdapter,
    HumanEvalAdapter.benchmark_id: HumanEvalAdapter,
    SWEBenchVerifiedAdapter.benchmark_id: SWEBenchVerifiedAdapter,
}


def get_adapter(benchmark_id: str) -> BenchmarkAdapter:
    """Return a new adapter instance for a benchmark ID."""
    try:
        factory = _ADAPTER_FACTORIES[benchmark_id]
    except KeyError as exc:
        known = ", ".join(sorted(_ADAPTER_FACTORIES))
        raise KeyError(f"Unknown benchmark adapter {benchmark_id!r}. Known adapters: {known}") from exc
    return factory()


def list_adapters() -> tuple[str, ...]:
    """Return built-in adapter IDs."""
    return tuple(sorted(_ADAPTER_FACTORIES))
