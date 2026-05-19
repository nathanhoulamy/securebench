import pytest

from securebench.adapters import HumanEvalAdapter, MMLUAdapter, SWEBenchVerifiedAdapter
from securebench.adapters.registry import get_adapter, list_adapters


def test_get_adapter_returns_known_built_in_adapters():
    assert isinstance(get_adapter("mmlu"), MMLUAdapter)
    assert isinstance(get_adapter("humaneval"), HumanEvalAdapter)
    assert isinstance(get_adapter("swebench_verified"), SWEBenchVerifiedAdapter)


def test_list_adapters_returns_known_ids():
    assert list_adapters() == ("humaneval", "mmlu", "swebench_verified")


def test_get_adapter_rejects_unknown_id():
    with pytest.raises(KeyError, match="Unknown benchmark adapter 'missing'"):
        get_adapter("missing")
