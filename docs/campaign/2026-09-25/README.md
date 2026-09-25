# Measurement campaign, 2026-09-24/25: native vs SecureBench

The same agent (Codex CLI 0.156.1, `gpt-6-luna`, reasoning effort `max`) on 60
admitted rows (30 DeepSWE, 30 Terminal-Bench 2.0), under the upstream harness
and verifier (native) and under SecureBench. There are 3 reps per task and
condition, 360 agent runs in total.

Start with `REPORT.md`. Everything that deviated from plan, or that the
campaign had to work around, is in `ISSUES.md` (I-01 to I-35). Pins, host
details and the full per-task configs are in `FREEZE.md`.

## Code that produced these results

- Rows, Oracles and harness: `50bffce` plus the changes committed in `65a3db0`:
  upstream image digests for 7 TB rows, restored instruction text, the kv-store
  int64 Oracle, and the Codex `prompt: instructions` option. The `--` separator
  before the prompt went in during rep 1 (ISSUES I-18); the one affected run was
  redone.
- Campaign tooling: `tools/native_baseline/` and `tools/campaign_aggregate.py`,
  committed in `e1088cd` in their final state. Driver fixes made during the run
  are dated in ISSUES (I-17, I-19, I-25, I-28, I-30, I-31, I-32).
- Upstream: `harbor-framework/terminal-bench-2@2fd12b88…` via Harbor 0.23.0;
  `datacurve-ai/deep-swe@e016041a…` via Pier 0.3.1.

## Files

| file | contents |
|---|---|
| `REPORT.md` | pass rates (per task, per benchmark with bootstrap CIs, paired B−A with sign-flip and Wilcoxon tests), verifier agreement (Phase 1 and 5, confusion matrices, Cohen's κ, every disagreement), attacks, infra errors, runtime/tokens/cost; each reported for all 30 DeepSWE rows and for the 10 rows without F2P-audit gaps |
| `records.jsonl` | one record per agent run (Phase 4; `rep` 1–3 analysed; rep 0 = smoke test, rep 5 = 27 runs made before the cut to 3 reps, excluded) |
| `aggregate/*.csv` | per-task and per-benchmark tables behind REPORT.md |
| `phase1-agreement.csv` | 794 fixed candidates: kind, native verdict, SecureBench verdict, agreement, grade source |
| `phase1-candidates.csv`, `phase1-kind-overrides.csv` | candidate provenance (qualification test node id, sha256) and kind labelling |
| `phase5-crossgrade.csv` | each real agent output re-graded by the other condition's verifier |
| `retries.jsonl` | every infrastructure-error retry and repair |
| `schedules/` | the seeded run order per rep |
| `resources.csv` | upstream vs SecureBench timeout, memory, CPU, network, image per task |
| `phase0/` | image digest checks, the TB image swap map, qualification logs, instruction diffs before the fix |
| `qualification/` | `tools.qualify_rows` records on this host (before and after the row changes) |

Paths inside these files that start with `runs/campaign/` refer to the raw
run directories (agent candidates, trial logs, SecureBench artifact stores).
Those are kept on the campaign host and not committed.
