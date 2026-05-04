import sys
import types

import pytest

from securebench.datasets import (
    MMLU_DATASET_ID,
    SWEBENCH_VERIFIED_DATASET_ID,
    HuggingFaceDatasetRef,
    mmlu_ref,
    swebench_verified_ref,
)


def install_fake_datasets(monkeypatch, rows):
    calls = []

    def load_dataset(*args, **kwargs):
        calls.append((args, kwargs))
        return rows

    module = types.SimpleNamespace(load_dataset=load_dataset)
    monkeypatch.setitem(sys.modules, "datasets", module)
    return calls


def test_mmlu_ref_points_at_cais_mmlu_subset():
    ref = mmlu_ref(config="computer_security", split="validation", revision="abc123", streaming=True)

    assert ref == HuggingFaceDatasetRef(
        name=MMLU_DATASET_ID,
        config="computer_security",
        split="validation",
        revision="abc123",
        streaming=True,
    )


def test_swebench_verified_ref_points_at_verified_test_split():
    ref = swebench_verified_ref()

    assert ref.name == SWEBENCH_VERIFIED_DATASET_ID
    assert ref.config is None
    assert ref.split == "test"


def test_huggingface_dataset_ref_loads_configured_dataset(monkeypatch):
    calls = install_fake_datasets(monkeypatch, rows=[])

    mmlu_ref(config="abstract_algebra", split="test", revision="rev", streaming=True).load()

    assert calls == [
        (
            (MMLU_DATASET_ID, "abstract_algebra"),
            {"split": "test", "streaming": True, "revision": "rev"},
        )
    ]


def test_huggingface_dataset_ref_loads_dataset_without_config(monkeypatch):
    calls = install_fake_datasets(monkeypatch, rows=[])

    swebench_verified_ref(split="test").load()

    assert calls == [
        (
            (SWEBENCH_VERIFIED_DATASET_ID,),
            {"split": "test", "streaming": False},
        )
    ]


def test_iter_rows_yields_rows_with_adapter_context(monkeypatch):
    rows = [
        {"question": "q1", "answer": 0},
        {"question": "q2", "answer": 1},
    ]
    install_fake_datasets(monkeypatch, rows=rows)

    loaded = mmlu_ref(config="abstract_algebra", split="test").load_rows(limit=1)

    assert len(loaded) == 1
    assert loaded[0].row == {"question": "q1", "answer": 0}
    assert loaded[0].context == {
        "config": "abstract_algebra",
        "split": "test",
        "row_idx": 0,
    }


def test_missing_datasets_dependency_raises_clear_error(monkeypatch):
    monkeypatch.delitem(sys.modules, "datasets", raising=False)
    monkeypatch.setitem(sys.modules, "datasets", None)

    with pytest.raises(ImportError, match=r"pip install -e '.\[hf\]'"):
        swebench_verified_ref().load()
