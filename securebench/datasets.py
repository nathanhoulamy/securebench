"""Dataset loading helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


MMLU_DATASET_ID = "cais/mmlu"
SWEBENCH_VERIFIED_DATASET_ID = "princeton-nlp/SWE-bench_Verified"


@dataclass(frozen=True)
class DatasetRow:
    """One dataset row plus adapter context derived from its row address."""

    row: dict[str, Any]
    context: dict[str, Any]


@dataclass(frozen=True)
class HuggingFaceDatasetRef:
    """Reference to a Hugging Face dataset split or subset."""

    name: str
    split: str
    config: str | None = None
    revision: str | None = None
    streaming: bool = False

    def load(self) -> Any:
        """Load the referenced Hugging Face dataset object."""
        load_dataset = _load_dataset()
        kwargs: dict[str, Any] = {
            "split": self.split,
            "streaming": self.streaming,
        }
        if self.revision is not None:
            kwargs["revision"] = self.revision
        if self.config is None:
            return load_dataset(self.name, **kwargs)
        return load_dataset(self.name, self.config, **kwargs)

    def iter_rows(self, *, limit: int | None = None) -> Iterator[DatasetRow]:
        """Yield rows with adapter context."""
        for row_idx, row in enumerate(self.load()):
            if limit is not None and row_idx >= limit:
                break
            yield DatasetRow(
                row=dict(row),
                context={
                    "config": self.config,
                    "split": self.split,
                    "row_idx": row_idx,
                },
            )

    def load_rows(self, *, limit: int | None = None) -> list[DatasetRow]:
        """Load rows eagerly into a list."""
        return list(self.iter_rows(limit=limit))


def mmlu_ref(
    *,
    config: str = "abstract_algebra",
    split: str = "test",
    revision: str | None = None,
    streaming: bool = False,
) -> HuggingFaceDatasetRef:
    """Return a reference for a MMLU subset."""
    return HuggingFaceDatasetRef(
        name=MMLU_DATASET_ID,
        config=config,
        split=split,
        revision=revision,
        streaming=streaming,
    )


def swebench_verified_ref(
    *,
    split: str = "test",
    revision: str | None = None,
    streaming: bool = False,
) -> HuggingFaceDatasetRef:
    """Return a reference for SWE-bench Verified."""
    return HuggingFaceDatasetRef(
        name=SWEBENCH_VERIFIED_DATASET_ID,
        split=split,
        revision=revision,
        streaming=streaming,
    )


def _load_dataset() -> Any:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise ImportError(
            "Hugging Face dataset loading requires the optional 'datasets' dependency. "
            "Install it with: pip install -e '.[hf]'"
        ) from exc
    return load_dataset
