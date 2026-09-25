# Pilot: adversarial candidates, terminal-bench/git-leak-recovery

Hand-authored candidates graded by both verifiers, to test whether a candidate
that does **not** solve the task can still obtain each condition's pass verdict.
Builder and graders: `tools/native_baseline/adversarial/git_leak_recovery.py`.
Raw results: `records.jsonl`.

## Method

- **native**: the real upstream harness (Harbor Docker replay via
  `phase1.native_grade`); reward from `/logs/verifier/reward.txt`.
- **securebench**: `verify_workspace()` — the capture + `VerificationEngine` +
  Oracle path that `phase1` uses for host-captured candidates.

Candidates are authored against native's model only, blind to SecureBench, then
graded on both. "Genuinely solves" is fixed per candidate by construction.
Builder: `tools/native_baseline/adversarial/git_leak_recovery.py`; driver:
`tools/native_baseline/adversarial/git_leak_builder.py`.

## Results (full-fidelity: native = real Harbor Docker replay)

| candidate | solves? | native | securebench | note |
|---|---|---|---|---|
| base (no work) | no | fail | fail | recovered_secret missing |
| reference (real fix) | yes | pass | pass | reproduces upstream repo checksum `2c3d63…` |
| reflog_only | no | **pass** | fail | secret alive via reflog; SB: `secret_remains_in_git_objects` |
| dangling_commit | no | **pass** | fail | secret under a dangling commit; SB: `secret_remains_in_git_objects` |
| alternates | no | fail | fail | broken in-container (both reject) |

**Two non-solving candidates obtain native's pass verdict; SecureBench blocks
both.** Native inspects only reachable refs and the objects `git fsck` prints on
`dangling` lines, so a secret blob kept alive via reflog or held under a dangling
commit is never inspected. SecureBench enumerates every object
(`cat-file --batch-all-objects`) and fails on `secret[` in any of them.

The `alternates` candidate (secret objects behind `objects/info/alternates`) is
rejected by **both**: SecureBench fails closed on the unsupported mechanism at
capture, and under the real container native's git cannot resolve the alternate
path, breaking the repo so the tests error. An earlier offline grade had scored
it native-pass; the Docker replay corrected it — recorded here as why
full-fidelity grading is used.
