# First-wave conversion qualification checklist

Use this checklist on the Linux host after checking out the exact conversion
commit. Tick a row only after its real pinned image has run end to end and its
dossier contains the resulting evidence. Deterministic unit tests are useful,
but they do not replace Linux/Docker qualification.

Inventory review disposition and runtime qualification are separate. The
first-wave control, `sqlite-db-truncate`, and `vulnerable-secret` sections
remain intentionally unchecked; only the three incrementally qualified rows
below currently have binary admission decisions. Global preflight and final
pack sign-off therefore remain incomplete.

## Run identity and host preflight

- [x] Branch is `split-verification-v2` and the tested implementation commit is
  `c3958a188db6565afed2a8de311c20bb036d7bdb`.
- [x] `git status --short` was clean at the tested implementation commit.
- [x] Host, date, OS, kernel, and architecture are recorded: 2026-08-26,
  Linux `7.0.0-29-generic`, x86_64.
- [x] `docker version` succeeds and Docker uses Linux/amd64 containers
  (Docker `29.7.2`).
- [x] Free disk space is sufficient for the pinned benchmark images and run
  output.
- [ ] The environment is installed with `python -m pip install -e '.[dev]'`.
- [x] `.venv/bin/pytest -q` passes (`577 passed, 19 skipped`; the stricter
  `-W error` run also passes).
- [x] `.venv/bin/securebench audit-self --output-dir /tmp/securebench-audit-self`
  passes (`25/25`, no warnings).
- [x] `.venv/bin/securebench audit --config benchmarks/terminal-bench/tester-linux.yaml --output-dir /tmp/terminal-bench-v2-audit`
  passes with all six selected rows (`25/25`, no warnings).
- [x] `.venv/bin/securebench audit --config benchmarks/deep-swe/tester-linux.yaml --output-dir /tmp/deep-swe-v2-audit`
  passes with all three selected rows (`13/13`, no warnings).
- [x] The selected harness credential mode is usable. For `auth: api_key`, the
  configured env file must contain `OPENAI_API_KEY`; run `securebench auth
  codex status` only when `auth: subscription` is selected. API-key-backed
  smoke runs completed, and no subscription login is configured.
- [x] Every selected task image uses and resolves to the digest declared in its
  row; no mutable
  tag was substituted.

Audit artifacts: `/tmp/securebench-precommit-audit-self`,
`/tmp/securebench-precommit-terminal-audit`, and
`/tmp/securebench-precommit-deep-audit`. The workspace filesystem had 188 GiB
free at preflight.

## Terminal-Bench

The tasks are ordered so these commands start exactly one new row at a time:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 1
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 2 --resume
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 3 --resume
```

Use a new `--output-dir` when intentionally rerunning a completed row. Confirm
the task ID in each result rather than inferring it from command order.

### Control: `terminal-bench/constraints-scheduling`

- [ ] The known-good control completes in the pinned Linux image.
- [ ] The captured candidate contains only `meeting_scheduled.ics` and remains
  within its declared byte bound.
- [ ] The Oracle, not guest output, issues the final verdict.
- [ ] Result path and execution digest are recorded: `_______________________`.

Control result: [ ] Passed  [ ] Failed

### `terminal-bench/sqlite-db-truncate`

- [ ] Missing `/app/recover.json` fails candidate capture or verification.
- [ ] The original/base state fails the intended recovery requirement.
- [ ] A reference recovery with at least seven distinct correct rows passes.
- [ ] Six correct rows plus duplicates fails; duplicates cannot inflate the
  recovery count.
- [ ] Extra candidate fields and unrelated rows cannot assert a verdict or
  change the host-owned expected set.
- [ ] Malformed JSON, an oversized file, a symlink, and a non-regular output are
  each rejected closed.
- [ ] The end-to-end Agent run completes in the pinned Linux image.
- [ ] The Candidate contains exactly the bounded declared artifact; inputs,
  logs, processes, and other workspace state are absent.
- [ ] Disposable state is removed and no container, mount, network rule, or
  helper state survives the case.
- [ ] Linux evidence and the execution digest are added to
  [`sqlite-db-truncate.md`](TerminalBench/sqlite-db-truncate.md).

Final status: [ ] Approved  [ ] Excluded

Evidence/reason: `___________________________________________________________`

### `terminal-bench/vulnerable-secret`

- [ ] Missing `/app/results.txt` fails candidate capture or verification.
- [ ] The original/base state fails the exact-secret requirement.
- [ ] The reference-extracted secret passes through the bounded UTF-8 parser.
- [ ] A plausible but incorrect `FLAG{...}` value fails.
- [ ] Leading/trailing whitespace follows the documented original semantics and
  does not allow extra content to bypass comparison.
- [ ] Malformed UTF-8, an oversized file, a symlink, and a non-regular output
  are each rejected closed.
- [ ] The end-to-end Agent run completes in the pinned Linux image.
- [ ] The Candidate contains exactly the bounded declared artifact; the
  executable, processes, logs, and other workspace state are absent.
- [ ] Disposable state is removed and no container, mount, or network rule
  survives the case.
- [ ] Linux evidence and the execution digest are added to
  [`vulnerable-secret.md`](TerminalBench/vulnerable-secret.md).

Final status: [ ] Approved  [ ] Excluded

Evidence/reason: `___________________________________________________________`

## Incremental Terminal-Bench conversions

Continue source-ordered Terminal rows one at a time after the first-wave pilot. For the fourth
Terminal row, resume the first three results and confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 4 --resume
```

### `terminal-bench/bn-fit-modify`

- [x] The source verifier and all scoring assertions were mapped to independent artifact evidence.
- [x] No Trusted Helper or Evaluation Adapter is required; Candidate code never executes during verification.
- [x] `securebench.strict-csv/v1` has closed finite byte, row, column, cell-count, and cell-size bounds plus malformed-input tests.
- [x] The unmodified/missing-output state fails through Oracle-owned Candidate-error handling.
- [x] A deterministic correct DAG, intervention DAG, and 10,000-row sample pass.
- [x] The known-good reference passes through the real digest-pinned Linux image and stopped-state capture path.
- [x] Targeted edge, intervention, distribution, row-count, and column mutants fail.
- [x] Candidate verdict claims cannot affect scoring.
- [x] Malformed CSV, invalid UTF-8, NULs, duplicate headers, ragged rows, symlinks, directories, and oversized files fail closed.
- [x] The live Agent run completes with `infrastructure_error: null` and the Oracle correctly rejects its semantically wrong artifacts.
- [x] The Candidate contains exactly three declared regular files and no input, log, process, or workspace state.
- [x] No SecureBench container, network, or volume survives the live run.
- [x] Linux evidence, fidelity notes, and result provenance are recorded in [`bn-fit-modify.md`](TerminalBench/bn-fit-modify.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion; qualified on Linux on 2026-08-25. Live execution digest
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.

For the fifth Terminal row, resume the first four results and confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 5 --resume
```

### `terminal-bench/cancel-async-tasks`

- [x] The complete source verifier and all five semantic scenarios are mapped to independent evidence.
- [x] The Candidate contains only bounded regular `/app/run.py`; installed state and live processes are excluded.
- [x] The public Adapter contains task-scenario and signal-forwarding plumbing but no assertions or expected answers.
- [x] Every case receives a fresh event ledger, credential, process supervisor, Evaluation, and correlation IDs.
- [x] Missing/base Candidate behavior is rejected by the host Oracle without becoming infrastructure failure.
- [x] The reviewed reference passes concurrency, one-slot serialization, all cancellation positions, and queued-task cleanup.
- [x] Sequential, unbounded, signal-ignoring, timeout, and forged-verdict mutants fail.
- [x] A real closure-introspection credential-forgery exploit fails because Candidate code receives no helper credential.
- [x] Premature Candidate cancellation is distinguished from trusted signal forwarding and rejected.
- [x] Symlink, directory, and oversized Candidate shapes fail closed.
- [x] The full pinned-image Docker matrix passes and leaves no Candidate-controlled verdict path.
- [x] The cheap-model Agent smoke run completes without infrastructure error and its result provenance is recorded.
- [x] No SecureBench container, network, or volume survives the model-backed smoke run.
- [x] Linux implementation, fidelity, and deterministic qualification evidence are recorded in [`cancel-async-tasks.md`](TerminalBench/cancel-async-tasks.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Qualified on Linux on 2026-08-26. The API-key-backed
`gpt-5.6-luna` smoke passed with score `1.0`, no infrastructure error, Candidate
digest `sha256:fe2a8afa945641feeb1a5326af7b542cf489f3cf1395e7e0e006578ea649c5e7`,
and execution digest
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.
The hardened verification digest is
`sha256:b25489e66468575eaa3967c1429a6c72e81b91537757f72281e4e26f4b26236c`.
Closure credential exposure, signal-readiness nondeterminism, and interrupted
container cleanup races found during adversarial qualification were fixed and
covered by deterministic and live regression tests before approval.

For the sixth Terminal row, resume the first five results and confirm the
selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 6 --resume
```

### `terminal-bench/chess-best-move`

- [x] The complete source verifier and its exact `strip().split()` semantics are mapped to host-only artifact scoring.
- [x] The Candidate contains only bounded regular `/app/move.txt`; the board image and live state are excluded.
- [x] No Adapter or Trusted Helper is needed, and Candidate content is never imported or executed.
- [x] The untouched pinned image fails Candidate capture and missing output is scored by the Oracle.
- [x] Both move orders and varied whitespace pass with the exact `e2e4`/`g2g4` multiset.
- [x] Missing, extra, duplicate, wrong, case-changed, and forged-verdict tokens fail.
- [x] Invalid UTF-8, symlink, directory, and oversized artifacts fail closed.
- [x] The reference passes stopped-Agent capture and host-only replay in the real pinned Linux image.
- [x] The cheap-model API smoke completes without infrastructure error and its incorrect move is rejected.
- [x] The one-row and full Terminal configuration audits pass without warnings.
- [x] Linux evidence, semantic fidelity, and result provenance are recorded in [`chess-best-move.md`](TerminalBench/chess-best-move.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux on 2026-08-26.
The pinned reference matrix passes `16/16`. The API-key-backed
`gpt-5.6-luna` smoke produced a semantically incorrect move and was correctly
rejected without infrastructure error. Execution digest:
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.

## DeepSWE

The tasks are ordered so these commands start exactly one new row at a time:

```bash
.venv/bin/securebench run --config benchmarks/deep-swe/tester-linux.yaml --limit 1
.venv/bin/securebench run --config benchmarks/deep-swe/tester-linux.yaml --limit 2 --resume
.venv/bin/securebench run --config benchmarks/deep-swe/tester-linux.yaml --limit 3 --resume
```

Use a new `--output-dir` when intentionally rerunning a completed row. Confirm
the task ID in each result rather than inferring it from command order.

### `deep-swe/cattrs-partial-structuring-recovery`

- [ ] The unmodified base commit fails the new behavior checks.
- [ ] The gold/reference patch passes through the real Python adapter.
- [ ] Targeted mutants for nested partial values, atomic collections,
  refinement, default factories, extra keys, and detailed validation fail.
- [ ] Attrs classes, dataclasses, TypedDicts, inheritance, `init=False`, exports,
  frozensets, and legacy error round-trips are exercised.
- [ ] Candidate attempts to forge an observation, import hidden Oracle code, or
  read another case are rejected or cannot affect the verdict.
- [ ] Every Challenge runs in a fresh Evaluation reconstructed from the same
  immutable base and captured patch.
- [ ] Patch path/size limits reject tests, framework paths, and oversized or
  malformed patches.
- [ ] No candidate process, filesystem state, mount, or network state survives
  between cases.
- [ ] Linux evidence and the execution digest are added to
  [`cattrs-partial-structuring-recovery.md`](DeepSWE/cattrs-partial-structuring-recovery.md).

Final status: [ ] Approved  [ ] Excluded

Evidence/reason: `___________________________________________________________`

### `deep-swe/fd-deterministic-multi-key-sorting`

- [ ] The unmodified base commit fails the new behavior checks.
- [ ] The gold/reference patch builds and passes through the real Rust/CLI
  adapter.
- [ ] Targeted mutants for key precedence, deterministic path tie-breaks,
  reverse, grouping, case sensitivity, missing values, natural ordering,
  seeded/unseeded random order, type order, and post-sort limits fail.
- [ ] Invalid modifier combinations and incompatibility with exec, batch exec,
  and detailed listing fail closed with bounded observations.
- [ ] Duplicate basenames, folded-equal paths, leading zeros, symlinks, mixed
  entry kinds, optional timestamps, and multiple roots are exercised.
- [ ] The pinned Linux filesystem exposes distinct creation/birth times for the
  created-time case; otherwise the row is excluded or redesigned rather than
  accepting a path-tie fallback.
- [ ] Malicious argv, path, output-volume, and filesystem scenarios stay inside
  the adapter and observation bounds.
- [ ] Every Challenge uses a fresh Evaluation and no process, file, mount, or
  network state survives between cases.
- [ ] Linux evidence, filesystem capability notes, and the execution digest are
  added to
  [`fd-deterministic-multi-key-sorting.md`](DeepSWE/fd-deterministic-multi-key-sorting.md).

Final status: [ ] Approved  [ ] Excluded

Evidence/reason: `___________________________________________________________`

### `deep-swe/updo-policy-alerting`

- [ ] The unmodified base commit fails the new behavior checks.
- [ ] The gold/reference patch passes through the real Go adapter and trusted
  HTTP recorder.
- [ ] Targeted mutants for failure/recovery thresholds, degraded/healthy
  transitions, SSL re-entry, counter resets, current snapshots, cooldown, and
  per-target configuration fail.
- [ ] Webhook bodies include required zero-valued fields and preserved custom
  headers; `EventNone` and suppressed decisions cause no request.
- [ ] Recovery/healthy delivery and cross-event non-recovery cooldown semantics
  are exercised at exact time boundaries.
- [ ] Forged credentials, wrong paths/tokens, undeclared network attempts,
  excessive requests, bodies, and headers are rejected closed.
- [ ] Helper credentials and request ledgers are fresh and correlated to the
  current check, Challenge, and Evaluation only.
- [ ] Every Challenge uses a fresh Evaluation; no candidate or Helper process,
  ledger, credential, mount, or network rule survives the case.
- [ ] Linux evidence and the execution digest are added to
  [`updo-policy-alerting.md`](DeepSWE/updo-policy-alerting.md).

Final status: [ ] Approved  [ ] Excluded

Evidence/reason: `___________________________________________________________`

## Final pack sign-off

- [ ] All six converted rows have exactly one binary final status: Approved or
  Excluded. “Pending”, “partial”, and “works locally” are not final statuses.
- [ ] Every Approved row demonstrates base failure, reference success,
  targeted-mutant rejection, malicious-candidate rejection, isolation, cleanup,
  and documented semantic fidelity.
- [ ] Each dossier records the tested commit, pinned image digest, Linux host,
  command/date, result location, and execution digest.
- [ ] Public and runtime roots contain no expected answers, hidden cases,
  assertions, scoring rules, gold changes, credentials, or remaining corpus.
- [ ] Candidate-controlled claims and guest test output are retained only as
  bounded observations, never as verdicts.
- [ ] A final `git status --short` and Docker/container/network inspection show
  no unintended state leaks.

Reviewer/date: `_____________________________________________________________`
