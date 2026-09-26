# Measurement campaign, 2026-09-26: native vs SecureBench, Claude Sonnet 5

The Luna campaign (`../2026-09-25/`) repeated with a different agent: Claude
Code 2.1.283, `claude-sonnet-5`, effort `medium`, on a Claude subscription. It
covers the same 60 admitted rows (30 DeepSWE, 30 Terminal-Bench 2.0;
`admitted-tasks.txt`), under the upstream harness and verifier (native) and
under SecureBench. There is **1 rep** per task and condition, 120 agent runs;
Luna had 3.

Start with `REPORT.md`, then `ISSUES.md` (S-01 to S-12). The campaign found and
fixed two SecureBench harness defects that also affected Luna (Luna ISSUES
I-37, I-38):
- the agent ran with a replaced HOME, so it lost the image's git identity and
  its Go, Rust and other toolchains (S-03, fixed before rep 1);
- stopped-worktree capture counted untracked ignored files (cargo `target/`,
  uv `.venv`), and rejected three candidates (S-10, fixed after rep 1; those
  runs were redone).

Two findings are left open for a decision:
- SecureBench grades nothing when the agent crashes or times out; upstream
  grades what the agent left (S-09).
- The 1 MiB agent-stdout bound hides token usage for most long SecureBench
  runs (S-08).

## Headline numbers (see REPORT.md for CIs and tests)

- Pass rate, native vs SecureBench: DeepSWE 0.267 vs 0.367, Terminal-Bench
  0.667 vs 0.667. With n=1 no paired difference is significant (DeepSWE p=0.61).
- Phase 5 cross-grading of real agent outputs: κ 0.852 (native outputs through
  the SecureBench verifier) and κ 0.879 (SecureBench outputs through native);
  7 disagreements on 5 rows: meriyah (both directions) and task-graph (both
  directions), which Luna I-35 already lists, plus helm-array-merge-strategies,
  dateutil-rfc5545-timezone-interop and cancel-async-tasks.
- Phase 1 is reused from Luna (model-independent): κ 0.929; malicious fixed
  candidates accepted by native 5/277, by SecureBench 0.
- No counted infrastructure errors. 29 runs hit the subscription's usage
  limit; the driver paused until each reset and redid the run (S-05, S-07).

## Code that produced these results

- Base: branch `split-verification-v2` at `7f50417`, plus the uncommitted
  changes listed in `FREEZE.md` and ISSUES S-02, S-03, S-07, S-10, S-12:
  `securebench/harnesses/{claude_code,codex}.py`,
  `securebench/candidates/capture.py`, `securebench/tester_run.py`, and the
  `CAMPAIGN_PROFILE=sonnet5` campaign tooling (`tools/native_baseline/profile.py`,
  `claude_agents.py`, and the profile-aware driver, freeze, phase5, key_scan and
  aggregator).
- Upstream: `harbor-framework/terminal-bench-2@2fd12b88…` via Harbor 0.23.0;
  `datacurve-ai/deep-swe@e016041a…` via Pier 0.3.1 (same as Luna).

## Files

| file | contents |
|---|---|
| `REPORT.md` | pass rates, paired B−A, verifier agreement (Phase 1 reused, Phase 5), attacks, runs where SecureBench graded no candidate, runtime/tokens/notional cost; all and clean-f2p scopes |
| `records.jsonl` | one record per counted agent run (rep 1) |
| `aggregate/*.csv` | per-task and per-benchmark tables behind REPORT.md |
| `phase5-crossgrade.csv` | each real agent output re-graded by the other condition's verifier |
| `retries.jsonl` | usage-limit set-asides and infrastructure retries |
| `schedules/` | the seeded run order (rep 1 and its relaunches) |
| `resources.csv`, `FREEZE.md` | upstream vs SecureBench limits per task; pins, host and per-task configs |

Raw run directories are in `runs/campaign-sonnet5/` (and the smoke tests in
`runs/campaign-sonnet5-smoke/`) on the campaign host; they are not committed.
