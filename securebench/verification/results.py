"""Append-only sanitized result persistence."""

from __future__ import annotations

import json
from pathlib import Path

from securebench.verification.models import VerificationResultV2


class ResultWriter:
    """Persist only the publishable projection of verification results."""

    def __init__(self, path: str | Path, *, run_id: str) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, result: VerificationResultV2) -> dict[str, object]:
        record = result.to_record(run_id=self.run_id)
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(encoded + "\n")
            file.flush()
        return record
