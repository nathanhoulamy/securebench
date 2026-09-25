# Native baseline and measurement campaign

Tooling for the campaign that compares the same agent under two conditions:

- **A. Native:** the upstream harness and verifier, unmodified: Harbor for
  Terminal-Bench 2.0 (`harbor-framework/terminal-bench-2` @ `2fd12b88…`) and
  Pier for DeepSWE (`datacurve-ai/deep-swe` @ `e016041a…`).
- **B. SecureBench:** `securebench.cli run` with per-task configs.

Both use Codex CLI 0.156.1, `gpt-6-luna`, reasoning effort `max`, the upstream
per-task agent timeout, and the upstream per-task memory. Results, pins and known
differences are in `docs/campaign/2026-09-25/`.

## Setup

```bash
python3 -m venv runs/campaign/native-venv
runs/campaign/native-venv/bin/pip install harbor==0.23.0 datacurve-pier==0.3.1
git clone https://github.com/harbor-framework/terminal-bench-2 runs/campaign/upstream/tb2
git -C runs/campaign/upstream/tb2 checkout 2fd12b88aafdd04a52c298e3940bcb189f9766d6
git clone https://github.com/datacurve-ai/deep-swe runs/campaign/upstream/deep-swe
git -C runs/campaign/upstream/deep-swe checkout e016041a6ccf8da29906afc9a3f5a8df940a1f78
```

The task lists are `runs/campaign/{ds,tb}-admitted-tasks-v2.jsonl`: the 30
committed DeepSWE rows, and the 30 Terminal-Bench rows with
`qualification_status=approved` in `docs/benchmark-conversions/inventory.csv`.
`OPENAI_API_KEY` is read from `.env` by the child processes only.

## Modules

| module | role |
|---|---|
| `campaign_configs.py` | one SecureBench config + one-row task file per task with upstream timeout, memory and capture cap; `configs/resources.csv` parity table |
| `codex_agents.py` | Pier/Harbor `Codex` subclasses that add a read-only post-run capture: DeepSWE working-tree diff, Terminal-Bench declared paths |
| `sb_run.py` | runs `securebench.cli run` in-process, logging timestamped progress events and raw Codex events (tokens) |
| `campaign.py` | Phase 3/4 driver: seeded task shuffle per rep, per-task random condition order, workers with memory budget, per-run pid locks, infrastructure retries (≤2), `repair`, `records` |
| `candidate_recorder.py` | pytest plugin that records every fixed candidate the qualification tests build |
| `replay_agents.py` | Pier/Harbor agents that install a fixed candidate (patch, or tar that replaces the declared paths) so the upstream verifier grades it |
| `phase1.py` | Phase 1: record → build → native → securebench (`harness.type: command`, host capture above the argv bound) → `phase1-agreement.csv` |
| `phase5.py` | Phase 5: cross-grade each real agent output with the other condition's verifier |
| `freeze.py` | writes `FREEZE.md` |
| `key_scan.py` | finds/redacts the API key under `runs/campaign/` |
| `../campaign_aggregate.py` | Phase 6: `REPORT.md` and CSVs |

## Run order

```bash
python -m tools.native_baseline.campaign_configs
python -m tools.native_baseline.freeze
python -m tools.native_baseline.phase1 record && python -m tools.native_baseline.phase1 build
python -m tools.native_baseline.phase1 native --workers 4
python -m tools.native_baseline.phase1 securebench --workers 3
python -m tools.native_baseline.phase1 table
python -m tools.native_baseline.campaign run --rep N --workers 6 --memory-gb 40   # N = 1..3
python -m tools.native_baseline.campaign repair && python -m tools.native_baseline.campaign records
python -m tools.native_baseline.phase5 --reps 1 2 3 --workers 4
python -m tools.native_baseline.key_scan --redact
python -m tools.campaign_aggregate
```

## Faithfulness notes

- Native runs use the upstream harness unchanged. The only addition is the
  post-run capture step, which runs after Codex exits and before upstream's own
  pre-artifacts and verification, and only reads the candidate state.
- Fixed-candidate replay mirrors upstream's `solution/solve.sh` for DeepSWE
  (apply, branch, `git add -A`, commit). For Terminal-Bench it removes the
  declared paths and extracts the candidate.
- Three Terminal-Bench rows (kv-store-grpc, hf-model-inference,
  headless-terminal) cannot be cross-graded by replay: their upstream tests
  need a live service or packages installed system-wide. The report marks them
  n/a.
- Everything the campaign had to work around is in the results' `ISSUES.md`.
