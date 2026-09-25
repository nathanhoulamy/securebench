"""Aggregate adversarial-candidate records into a summary table.

Reads every runs/campaign-adversarial/<pack>/<row>/records.jsonl and prints, and
writes JSON, the per-row and overall attack tallies:
  - native attacks: candidates with native_verdict==pass and genuinely_solves==False
  - securebench attacks: same for securebench_verdict
  - base/reference sanity per row.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "runs" / "campaign-adversarial"


def main() -> int:
    rows = {}
    for rec_file in sorted(RUNS.glob("*/*/records.jsonl")):
        recs = [json.loads(l) for l in rec_file.read_text().splitlines() if l.strip()]
        if not recs:
            continue
        row = recs[0]["row"]
        rows[row] = recs
    n_native = n_sb = 0
    native_rows = []
    sb_rows = []
    print(f"{'row':55s} {'native_atk':10s} {'sb_atk':7s} base/ref")
    for row, recs in sorted(rows.items()):
        na = [r for r in recs if r.get("native_verdict") == "pass" and not r["genuinely_solves"]]
        sa = [r for r in recs if r.get("securebench_verdict") == "pass" and not r["genuinely_solves"]]
        base = next((r for r in recs if r["candidate"] == "base"), None)
        ref = next((r for r in recs if r["candidate"] == "reference"), None)
        sanity = ""
        if base:
            sanity += f"base n={base.get('native_verdict')}/s={base.get('securebench_verdict')} "
        if ref:
            sanity += f"ref n={ref.get('native_verdict')}/s={ref.get('securebench_verdict')}"
        if na:
            n_native += 1
            native_rows.append((row, [r["candidate"] for r in na]))
        if sa:
            n_sb += 1
            sb_rows.append((row, [r["candidate"] for r in sa]))
        print(f"{row:55s} {len(na):10d} {len(sa):7d} {sanity}")
    print(f"\nrows graded: {len(rows)}")
    print(f"rows with a NATIVE attack: {n_native}")
    print(f"rows with a SECUREBENCH attack: {n_sb}")
    for row, cands in native_rows:
        print(f"  native  {row}: {cands}")
    for row, cands in sb_rows:
        print(f"  securebench {row}: {cands}")
    summary = {"rows_graded": len(rows), "native_attack_rows": native_rows,
               "securebench_attack_rows": sb_rows}
    (RUNS / "summary.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
