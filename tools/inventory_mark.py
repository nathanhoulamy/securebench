"""Mark inventory rows as implemented and approved, preserving the CSV convention.

Usage::

    python -m tools.inventory_mark DeepSWE bandit-structured-nosec-directives ...
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "docs" / "benchmark-conversions" / "inventory.csv"
ALWAYS_QUOTED = {"final_verdict", "disposition", "verification_pattern"}


def _render(name: str, value: str) -> str:
    if name in ALWAYS_QUOTED or "," in value or '"' in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def main() -> int:
    benchmark, tasks = sys.argv[1], set(sys.argv[2:])
    rows = list(csv.DictReader(PATH.open(newline="")))
    fields = list(rows[0])
    found = set()
    for row in rows:
        if row["benchmark"] == benchmark and row["task"] in tasks:
            row["implementation_status"] = "implemented"
            row["qualification_status"] = "approved"
            found.add(row["task"])
    missing = tasks - found
    if missing:
        raise SystemExit(f"not in inventory: {sorted(missing)}")
    lines = [",".join(fields)] + [",".join(_render(f, r[f]) for f in fields) for r in rows]
    PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    approved = sum(1 for r in rows if r["qualification_status"] == "approved")
    print(f"marked {len(found)}; approved total now {approved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
