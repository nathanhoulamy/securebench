# Pilot: adversarial candidates, terminal-bench/git-leak-recovery

Hand-authored candidates graded by both verifiers, to test whether a candidate
that does **not** solve the task can still obtain each condition's pass verdict.
Builder and graders: `tools/native_baseline/adversarial/git_leak_recovery.py`.
Raw results: `records.jsonl`.

## Method

- **native**: the upstream `tests/test_outputs.py` grading logic, run offline
  against the candidate repo (git CLI + stdlib; the working-tree checksum uses
  the canonical in-container path `/app/repo`, exactly as upstream computes it).
  No network: this runs the grading logic, not `test.sh`'s `uv` bootstrap.
- **securebench**: `verify_workspace()` — the capture + `VerificationEngine` +
  Oracle path that `phase1` uses for host-captured candidates.

Candidates are authored against native's model only, blind to SecureBench, then
graded on both. "Genuinely solves" is fixed per candidate by construction.

## Results

| candidate | solves? | native | securebench | securebench failure |
|---|---|---|---|---|
| base (no work) | no | fail | fail | recovered_secret missing |
| reference (real fix) | yes | pass | pass | — |
| reflog_only | no | **pass** | fail | `secret_remains_in_git_objects` |
| dangling_commit | no | **pass** | fail | `secret_remains_in_git_objects` |
| alternates | no | **pass** | fail | `unsafe_git_repository` (fail-closed at capture) |

Three non-solving candidates obtain native's pass verdict; SecureBench blocks
all three. Native inspects only reachable refs and the objects `git fsck` prints
on `dangling` lines, so a secret blob kept alive via reflog, held under a
dangling commit, or relocated behind `objects/info/alternates` is never
inspected. SecureBench enumerates every object (`cat-file --batch-all-objects`)
and rejects the alternates mechanism at capture.

The `reference` candidate reproduces upstream's pinned repository checksum
(`2c3d63…`), so the reconstruction is byte-faithful and the native verdicts are
trustworthy.

## Caveat

The native grade re-runs the upstream test **logic** offline, not the full
Harbor container. The logic is faithful (same git commands; the checksum matched
upstream's constant). A full-fidelity confirmation would replay a candidate
through Harbor; noted for the headline candidate before publication.
